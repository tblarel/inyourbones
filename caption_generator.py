import os
import json
import re
import datetime
from collections import defaultdict
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import base64

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
gs_client = gspread.authorize(creds)

INPUT_FILE = 'top_articles.json'
OUTPUT_FILE = 'top_articles_with_captions.json'
SHEET_NAME = 'InYourBones Daily Music News'

CAPTION_PROMPT = (
    "Write a short, upbeat social media caption for a music news headline. "
    "Use a fun and engaging tone, include emojis if appropriate, and make it feel human and fresh. "
    "Avoid using the phrases 'get ready', 'can't wait', 'don't miss', 'breaking news', or 'mark your calendars' excessively. "
    "Vary your structure across posts and keep captions under 25 words."
)

LIMITED_PHRASES = ["get ready", "can't wait", "don't miss", "breaking news", "mark your calendars"]
USED_PHRASES = defaultdict(int)
PHRASE_POSITION_COUNTS = defaultdict(lambda: defaultdict(int))
USED_INTROS = defaultdict(int)
MAX_TOTAL_PHRASE_USAGE = 2
MAX_POSITION_PHRASE_USAGE = 2
MAX_INTRO_USAGE = 2
MAX_ATTEMPTS = 5
STRICT_MODE = False

# --- LOAD ARTICLES ---
def load_articles():
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

# --- PHRASE POSITION CHECK ---
def analyze_phrase_positions(text):
    results = []
    words = text.lower().split()
    joined = " ".join(words)
    for phrase in LIMITED_PHRASES:
        if phrase in joined:
            start_index = joined.find(phrase)
            position = "start" if start_index < 30 else ("middle" if start_index < 60 else "end")
            results.append((phrase, position))
    return results

# --- PHRASE USAGE CHECK ---
def phrase_usage_exceeded(text):
    phrase_positions = analyze_phrase_positions(text)
    for phrase, pos in phrase_positions:
        if PHRASE_POSITION_COUNTS[phrase][pos] >= MAX_POSITION_PHRASE_USAGE:
            print(f"❌ Phrase '{phrase}' overused in position '{pos}'")
            if STRICT_MODE: return True
        if USED_PHRASES[phrase] >= MAX_TOTAL_PHRASE_USAGE:
            print(f"❌ Phrase '{phrase}' overused globally")
            if STRICT_MODE: return True
    return False

# --- VALIDATE CAPTION ---
def validate_caption(caption, soft=False):
    if not caption.strip():
        print("❌ Caption is empty")
        return False
    phrase_exceeded = phrase_usage_exceeded(caption)
    intro_key = " ".join(re.findall(r'\w+', caption.lower())[:4])
    intro_exceeded = USED_INTROS[intro_key] >= MAX_INTRO_USAGE

    if phrase_exceeded or intro_exceeded:
        if phrase_exceeded:
            print(f"❌ Phrase limit exceeded in caption")
        if intro_exceeded:
            print(f"❌ Intro pattern overused: '{intro_key}'")
        return not STRICT_MODE and soft
    return True

# --- RECORD USAGE ---
def record_usage(caption):
    phrase_positions = analyze_phrase_positions(caption)
    for phrase, pos in phrase_positions:
        USED_PHRASES[phrase] += 1
        PHRASE_POSITION_COUNTS[phrase][pos] += 1
        print(f"✅ Tracking phrase '{phrase}' in position '{pos}'")
    intro_key = " ".join(re.findall(r'\w+', caption.lower())[:4])
    USED_INTROS[intro_key] += 1
    print(f"✅ Tracking intro: '{intro_key}'")

# --- GENERATE CAPTION ---
def generate_caption_for_title(title, force_unique=False):
    full_prompt = f"{CAPTION_PROMPT}\n\nHeadline: {title}"
    if force_unique:
        full_prompt += "\nAvoid using any previous structure or phrase pattern."

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a music-savvy, fun social media editor."},
            {"role": "user", "content": full_prompt}
        ],
        temperature=0.85,
        max_tokens=60,
        stream=False
    )
    return response.choices[0].message.content.strip()

# --- SYNC TO GOOGLE SHEET ---
def update_sheet_with_captions(final_articles):
    now = datetime.datetime.now()
    month_year = now.strftime('%B %Y')
    sheet_title = f"{month_year} (selects)"
    print(f"\n🔄 Updating Google Sheet: {sheet_title}")

    try:
        spreadsheet = gs_client.open(SHEET_NAME)
        worksheet = spreadsheet.worksheet(sheet_title)
        data = worksheet.get_all_values()

        headers = data[0]
        rows = data[1:]

        if 'Caption' not in headers:
            headers.append('Caption')
            worksheet.update('A1', [headers])

        caption_col_index = headers.index('Caption')

        updates = []
        for i, row in enumerate(rows):
            row_title = row[0].strip()
            for article in final_articles:
                if article['title'].strip() == row_title:
                    while len(row) <= caption_col_index:
                        row.append("")
                    row[caption_col_index] = article['caption']
                    updates.append((i+2, row))

        for row_num, row_data in updates:
            worksheet.update(f"A{row_num}", [row_data])

        print(f"✅ Updated {len(updates)} rows in '{sheet_title}'")
    except Exception as e:
        print(f"❌ Error updating sheet: {e}")

# --- MAIN ---
def main():
    articles = load_articles()

    for article in articles:
        print(f"\n➡️ Generating caption for: {article['title']}")
        caption = ""
        fallback_used = False
        for attempt in range(MAX_ATTEMPTS):
            caption = generate_caption_for_title(article['title'], force_unique=(attempt >= 2))
            if validate_caption(caption):
                print(f"✅ Valid caption: {caption}")
                record_usage(caption)
                break
            elif validate_caption(caption, soft=True):
                print(f"⚠️ Soft-approved fallback caption: {caption}")
                record_usage(caption)
                fallback_used = True
                break
            else:
                print(f"🔁 Retry attempt {attempt+1} for: {article['title']}")

        if not caption.strip():
            caption = "🎶 New headline in music — check it out!"
            print(f"⚠️ Full fallback used for: {article['title']}")
        elif fallback_used:
            print(f"⚠️ Final fallback-approved caption accepted: {caption}")

        article['caption'] = caption

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(articles, f, indent=2)

    print(f"\n✅ Saved {len(articles)} articles with captions to '{OUTPUT_FILE}'")

    update_sheet_with_captions(articles)

if __name__ == '__main__':
    main()
