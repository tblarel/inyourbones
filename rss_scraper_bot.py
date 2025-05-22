# rss_scraper_bot.py
import os
import base64
import feedparser
import datetime
import gspread
import json
from dateutil import parser
from oauth2client.service_account import ServiceAccountCredentials
import pytz

# --- CONFIG ---
RSS_FEEDS = [
    'https://pitchfork.com/rss/news/',
    'https://www.stereogum.com/feed/',
    'https://consequence.net/feed/',
    'https://www.nme.com/news/rss',
    'https://www.brooklynvegan.com/feed/',
    'https://www.spin.com/feed/',
    'https://www.billboard.com/feed/',
    'https://www.rollingstone.com/music/music-news/feed/',
    'https://www.pastemagazine.com/music/rss/',
]

GOOGLE_SHEET_NAME = 'InYourBones Daily Music News'
MAX_RESULTS = 50

# --- LOAD FILTERS ---
with open('filters.json', 'r', encoding='utf-8') as f:
    filter_config = json.load(f)

EXCLUDE_KEYWORDS = filter_config.get("excluded_keywords", [])

# --- SETUP GOOGLE SHEETS ---
scope = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/spreadsheets',
         'https://www.googleapis.com/auth/drive.file',
         'https://www.googleapis.com/auth/drive']

creds_path = "creds.json"
creds_b64 = os.getenv("CREDS_B64")

if creds_b64:
    with open(creds_path, "w", encoding="utf-8") as f:
        f.write(base64.b64decode(creds_b64).decode("utf-8"))
    print("✅ Created creds.json from CREDS_B64")
elif not os.path.exists(creds_path):
    print("❌ No credentials available. Exiting.")
    exit(1)
else:
    print("✅ Using local creds.json file")

client = gspread.authorize(creds)
print("Available spreadsheets:", [s.title for s in client.openall()])
spreadsheet = client.open(GOOGLE_SHEET_NAME)

# --- HELPER ---
def is_from_yesterday_pst(published_dt):
    pacific = pytz.timezone("America/Los_Angeles")
    now_pst = datetime.datetime.now(pacific)
    yesterday_pst = now_pst - datetime.timedelta(days=1)

    if not published_dt:
        return False

    published = datetime.datetime(*published_dt[:6], tzinfo=datetime.timezone.utc).astimezone(pacific)
    return published.date() == yesterday_pst.date()

def is_relevant(title):
    title_lower = title.lower()
    return not any(keyword in title_lower for keyword in EXCLUDE_KEYWORDS)

# --- MAIN SCRAPER ---
def fetch_recent_articles():
    results = []
    seen_titles = set()
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            if is_from_yesterday_pst(entry.published_parsed) and is_relevant(entry.title):
                title = entry.title.strip()
                if title not in seen_titles:
                    seen_titles.add(title)
                    results.append({
                        'title': title,
                        'link': entry.link,
                        'source': feed.feed.title,
                        'published': entry.published
                    })
    print(f"Fetched {len(results)} articles from yesterday (PST) (deduplicated by title)")
    return sorted(results, key=lambda a: a['published'], reverse=True)

# --- WRITE TO MONTHLY SHEET ---
def update_monthly_sheet(articles):
    pacific = pytz.timezone("America/Los_Angeles")
    now = datetime.datetime.now(pacific)
    yesterday = now - datetime.timedelta(days=1)
    sheet_tab = now.strftime('%B %Y')
    date_str = yesterday.strftime('%Y-%m-%d')
    print(f"Preparing to update sheet: {sheet_tab} for date {date_str}")

    try:
        worksheet = spreadsheet.worksheet(sheet_tab)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=sheet_tab, rows="1000", cols="4")

    all_values = worksheet.get_all_values()
    print(f"Current sheet row count: {len(all_values)}")
    headers = all_values[0] if all_values else ['Title', 'Link', 'Source', 'Published']
    filtered_values = []
    removed_count = 0

    for row in all_values[1:]:
        if row and len(row) > 3:
            try:
                parsed_date = parser.parse(row[3]).astimezone(pacific).date()
                if parsed_date.strftime('%Y-%m-%d') != date_str:
                    filtered_values.append(row)
                else:
                    removed_count += 1
            except Exception as e:
                print(f"Error parsing row date: {row[3]} -> {e}")
                filtered_values.append(row)
    print(f"Removed {removed_count} rows from {date_str}")

    new_rows = [[a['title'], a['link'], a['source'], a['published']] for a in articles[:MAX_RESULTS]]
    unique_rows = []
    seen = set()
    for row in new_rows:
        if row[0] not in seen:
            seen.add(row[0])
            unique_rows.append(row)
    print(f"Appending {len(unique_rows)} new unique rows")

    final_data = [headers] + filtered_values + unique_rows
    worksheet.clear()
    worksheet.update(values=final_data, range_name='A1')

if __name__ == '__main__':
    articles = fetch_recent_articles()
    update_monthly_sheet(articles)
    print(f"Posted {min(len(articles), MAX_RESULTS)} unique articles to current month's sheet.")

    with open('latest_articles.json', 'w', encoding='utf-8') as f:
        json.dump(articles[:MAX_RESULTS], f, indent=2)
