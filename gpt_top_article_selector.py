import os
import re
import json
import datetime
import gspread
from dateutil import parser
from llm import chat
from oauth2client.service_account import ServiceAccountCredentials
from gspread.http_client import BackOffHTTPClient
import pytz
import base64

GOOGLE_SHEET_NAME = 'InYourBones Daily Music News'

# --- HANDLE CREDS FROM ENV ---
creds_b64 = os.getenv("CREDS_B64")
if creds_b64:
    with open("creds.json", "w", encoding="utf-8") as f:
        decoded = base64.b64decode(creds_b64).decode("utf-8")
        f.write(decoded)
else:
    print("⚠️ CREDS_B64 not found in environment. Google Sheets access may fail.")

# --- GOOGLE SHEETS SETUP ---
scope = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/spreadsheets',
         'https://www.googleapis.com/auth/drive.file',
         'https://www.googleapis.com/auth/drive']

creds = ServiceAccountCredentials.from_json_keyfile_name('creds.json', scope)
gsheet = gspread.authorize(creds, http_client=BackOffHTTPClient)  # retries 429/5xx
print("✅ Google Sheets connected.")
spreadsheet = gsheet.open(GOOGLE_SHEET_NAME)

# --- LOAD ARTICLES FROM JSON ---
def load_articles(filepath='latest_articles.json'):
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

# --- DUPLICATE DETECTION ---
# Common English + music-news words that appear across unrelated stories
# ("X Announce New Album: Hear..."), so sharing them doesn't mean it's the same story.
GENERIC_WORDS = set("""
a an the and or but of in on at to for with from by as is are was were be been it its this that these those
his her their our your my he she they we you i me him them who what why how when where which than then so not no
s vs via into onto over under up out off about after before amid during since until again just more most all any
will would can could may might has have had do does did new first last next year years
announce announces announced announcing announcement tour tours touring dates date album albums lp ep record records
single singles song songs track tracks video videos music musical share shares shared sharing release releases released
releasing drop drops dropped debut debuts debuted unveil unveils unveiled reveal reveals revealed return returns
returned watch hear listen stream streaming live perform performs performed performance show shows concert concerts
festival festivals lineup world north american europe uk us details detail premiere premieres cover covers covered
back today tonight week weekend news report reports review interview official officially plus featuring feat ft
anniversary edition deluxe reissue expanded box set sets play plays played playing join joins joined collab
collaboration together special guest guests headline headlining headliner headliners
""".split())

def content_words(title):
    title = re.sub(r"['’]s\b", "", title.lower())
    return {w for w in re.findall(r"[^\W_]+", title)
            if len(w) > 1 and not w.isdigit() and w not in GENERIC_WORDS}

def normalize_title(title):
    title = title.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    return " ".join(title.split()).lower()  # also collapses non-breaking spaces

def find_article(line, articles):
    """Match a line of GPT's reply to an article, tolerating quote/spacing changes or a trimmed title."""
    target = normalize_title(line)
    exact = [a for a in articles if normalize_title(a['title']) == target]
    if exact or len(target) < 20:
        return exact[0] if exact else None
    return next((a for a in articles if target in normalize_title(a['title'])), None)

def is_same_story(article, others):
    """Headlines sharing 2+ distinctive words (artist, album, event) are treated as the same story."""
    words = content_words(article['title'])
    return any(len(words & content_words(o['title'])) >= 2 for o in others)

# --- RANK WITH GPT ---
def rank_top_articles(articles, count=5):
    MAX_HEADLINES_FOR_RANKING = 100
    EXTRA_PICKS = 3  # ranked backups, used if a pick turns out to duplicate another story
    pick_count = count + EXTRA_PICKS
    input_articles = articles[:MAX_HEADLINES_FOR_RANKING]
    headlines = [f"- {a['title']}" for a in input_articles]

    prompt = f"""
You are a music editor for a positive, fan-driven live music publication. From the list of music news headlines below, select the {pick_count} most exciting, uplifting, and buzzworthy ones that would perform well on social media and align with our publication's upbeat tone.

Avoid stories that are primarily negative (e.g. illnesses, arrests, scandals, cancellations). Focus on live show announcements, tours, new music, fun moments, and artist milestones.

Make sure to select a variety of artists — do not include multiple headlines about the same artist or event.

{chr(10).join(headlines)}

Return exactly {pick_count} headlines, ranked best first, each on a new line, using the original wording.
"""

    content = chat(
        [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )

    # Strip bullets/numbering ("- ", "1. ") some models add
    selected_titles = [re.sub(r'^(?:[-*•]|\d+[.)])\s*', '', t.strip()) for t in content.splitlines() if t.strip()]

    top_articles = []
    for t in selected_titles:
        a = find_article(t, articles)
        if a and a not in top_articles and not is_same_story(a, top_articles):
            top_articles.append(a)
        if len(top_articles) >= count:
            break

    print(f"🧠 GPT selected {len(top_articles)} unique articles.")

    if len(top_articles) < count:
        print(f"⚠️ Filling {count - len(top_articles)} slot(s) with non-GPT fallback articles.")
        for candidate in articles:
            if candidate not in top_articles and not is_same_story(candidate, top_articles):
                top_articles.append(candidate)
                if len(top_articles) >= count:
                    break

    return top_articles[:count]

# --- SAVE SELECTED ARTICLES ---
def save_top_articles(articles, filepath='top_articles.json'):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(articles, f, indent=2)

# --- WRITE TO MONTHLY SELECTS SHEET ---
def update_selects_sheet(articles):
    pacific = pytz.timezone("America/Los_Angeles")
    now = datetime.datetime.now(pacific)
    month_tab = now.strftime('%B %Y (selects)')

    try:
        worksheet = spreadsheet.worksheet(month_tab)
        print(f"📝 Writing to sheet tab: {month_tab}")
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=month_tab, rows="1000", cols="6")
        worksheet.append_row(['Title', 'Link', 'Source', 'Published', 'Caption', 'Image'])
        print(f"➕ Created new sheet tab: {month_tab}")

    all_values = worksheet.get_all_values()
    headers = all_values[0] if all_values else ['Title', 'Link', 'Source', 'Published', 'Caption', 'Image']
    while len(headers) < 6:
        headers.append('')

    # Create set of (title, link) to detect duplicates
    existing_keys = set()
    for row in all_values[1:]:
        if len(row) >= 2:
            key = (row[0].strip(), row[1].strip())
            existing_keys.add(key)

    # A re-run replaces earlier picks for the same news day, except rows already
    # approved/rejected in the dashboard (column G) or picked again this run
    news_days = {parser.parse(a['published']).astimezone(pacific).date() for a in articles}
    new_keys = {(a['title'].strip(), a['link'].strip()) for a in articles}
    filtered_values = []
    removed_count = 0
    for row in all_values[1:]:
        if len(row) >= 4:
            try:
                parsed_date = parser.parse(row[3]).astimezone(pacific).date()
                reviewed = len(row) > 6 and row[6].strip()
                if parsed_date not in news_days or (row[0].strip(), row[1].strip()) in new_keys or reviewed:
                    while len(row) < len(headers):
                        row.append('')
                    filtered_values.append(row)
                else:
                    removed_count += 1
            except Exception as e:
                print(f"⚠️ Error parsing date '{row[3]}': {e}")
                while len(row) < len(headers):
                    row.append('')
                filtered_values.append(row)
    print(f"🗑️ Removed {removed_count} earlier unreviewed pick(s) for {', '.join(sorted(map(str, news_days)))}")

    # Add new rows
    new_rows = []
    for a in articles:
        key = (a['title'].strip(), a['link'].strip())
        if key in existing_keys:
            print(f"⏭️ Skipping duplicate: {a['title']}")
            continue

        caption = f"{a['title'].split(':')[0]} – more to come..."  # Placeholder
        row = [
            a['title'],
            a['link'],
            a['source'],
            a['published'],
            caption,
            a.get('image', '')
        ]
        print(f"✅ Adding row: {row[0][:40]}... | Image: {row[5]}")
        new_rows.append(row)

    final_data = [headers] + filtered_values + new_rows
    # Write before clearing leftover rows so a failed API call can't leave the tab empty
    worksheet.update(values=final_data, range_name='A1')
    if len(all_values) > len(final_data):
        worksheet.batch_clear([f"A{len(final_data) + 1}:Z{len(all_values)}"])
    print(f"✅ Sheet updated with {len(new_rows)} new row(s).")

# --- MAIN ---
if __name__ == '__main__':
    print("🔄 Loading latest articles...")
    all_articles = load_articles()

    print("🧠 Selecting top 5 with GPT...")
    top_five = rank_top_articles(all_articles, count=5)

    print("💾 Saving to top_articles.json...")
    save_top_articles(top_five)

    print("📤 Writing to selects sheet...")
    update_selects_sheet(top_five)

    print("🎉 Done.")
