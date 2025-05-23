import os
import json
import datetime
import gspread
from dateutil import parser
from openai import OpenAI
from oauth2client.service_account import ServiceAccountCredentials
import pytz
import base64

GOOGLE_SHEET_NAME = 'InYourBones Daily Music News'

# --- SETUP OPENAI ---
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
gsheet = gspread.authorize(creds)
print("Available spreadsheets:", [s.title for s in gsheet.openall()])
spreadsheet = gsheet.open(GOOGLE_SHEET_NAME)

# --- LOAD ARTICLES FROM JSON ---
def load_articles(filepath='latest_articles.json'):
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

# --- RANK WITH GPT ---
def rank_top_articles(articles, count=5):
    MAX_HEADLINES_FOR_RANKING = 60
    input_articles = articles[:MAX_HEADLINES_FOR_RANKING]
    headlines = [f"- {a['title']}" for a in input_articles]

    prompt = f"""
You are a music editor for a positive, fan-driven live music publication. From the list of music news headlines below, select the {count} most exciting, uplifting, and buzzworthy ones that would perform well on social media and align with our publication's upbeat tone.

Avoid stories that are primarily negative (e.g. illnesses, arrests, scandals, cancellations). Focus on live show announcements, tours, new music, fun moments, and artist milestones.

Make sure to select a variety of artists — do not include multiple headlines about the same artist or event.

{chr(10).join(headlines)}

Return exactly {count} headlines, each on a new line, using the original wording.
"""

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )

    content = response.choices[0].message.content.strip()
    selected_titles = [t.lstrip("- ").strip() for t in content.splitlines() if t.strip()]

    seen_titles = set()
    seen_keywords = set()
    top_articles = []
    for t in selected_titles:
        for a in articles:
            if a['title'] == t and t not in seen_titles:
                # Check for similar keyword overlap
                keywords = set(a['title'].lower().split())
                if all(len(keywords & set(k.lower().split())) < 3 for k in seen_keywords):
                    top_articles.append(a)
                    seen_titles.add(t)
                    seen_keywords.add(a['title'])
                    break

    print(f"GPT returned {len(top_articles)} unique articles.")

    # Fill in missing slots with non-overlapping fallbacks
    if len(top_articles) < count:
        fallback_pool = [a for a in articles if a['title'] not in seen_titles]
        for candidate in fallback_pool:
            candidate_keywords = set(candidate['title'].lower().split())
            if all(len(candidate_keywords & set(k.lower().split())) < 3 for k in seen_keywords):
                top_articles.append(candidate)
                seen_titles.add(candidate['title'])
                seen_keywords.add(candidate['title'])
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
    today_str = now.strftime('%Y-%m-%d')

    try:
        worksheet = spreadsheet.worksheet(month_tab)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=month_tab, rows="1000", cols="4")
        worksheet.append_row(['Title', 'Link', 'Source', 'Published'])

    all_values = worksheet.get_all_values()
    headers = all_values[0] if all_values else ['Title', 'Link', 'Source', 'Published']
    filtered_values = []
    removed_count = 0

    for row in all_values[1:]:
        if row and len(row) > 3:
            try:
                parsed_date = parser.parse(row[3]).astimezone(pacific).date()
                if parsed_date.strftime('%Y-%m-%d') != today_str:
                    filtered_values.append(row)
                else:
                    removed_count += 1
            except Exception as e:
                print(f"Error parsing row date: {row[3]} -> {e}")
                filtered_values.append(row)
    print(f"Removed {removed_count} rows from today in selects sheet")

    new_rows = [[a['title'], a['link'], a['source'], a['published']] for a in articles]
    unique_rows = []
    seen = set()
    for row in new_rows:
        if row[0] not in seen:
            seen.add(row[0])
            unique_rows.append(row)

    final_data = [headers] + filtered_values + unique_rows
    worksheet.clear()
    worksheet.update(values=final_data, range_name='A1')

if __name__ == '__main__':
    all_articles = load_articles()
    top_five = rank_top_articles(all_articles, count=5)
    save_top_articles(top_five)
    update_selects_sheet(top_five)
    print("Top 5 articles selected and posted to selects sheet.")
