import os
import sys
import argparse
import base64
import feedparser
import datetime
import gspread
import json
from dateutil import parser
from oauth2client.service_account import ServiceAccountCredentials
from gspread.http_client import BackOffHTTPClient
import pytz
import requests
from bs4 import BeautifulSoup

# --- HANDLE CREDS FROM ENV ---
creds_b64 = os.getenv("CREDS_B64")
if creds_b64:
    with open("creds.json", "w", encoding="utf-8") as f:
        decoded = base64.b64decode(creds_b64).decode("utf-8")
        f.write(decoded)
else:
    print("⚠️ CREDS_B64 not found in environment. Google Sheets access may fail.")

# --- CONFIG ---
RSS_FEEDS = [
    # 'https://news.google.com/rss/search?q=music&hl=en-US&gl=US&ceid=US:en',
    # 'https://news.google.com/rss/search?q=new+music+releases&hl=en-US&gl=US&ceid=US:en',
    # 'https://news.google.com/rss/search?q=music+tour+2025&hl=en-US&gl=US&ceid=US:en',
    'https://pitchfork.com/rss/news/',
    'https://www.stereogum.com/feed/',
    'https://consequence.net/feed/',
    'https://www.nme.com/news/rss',
    'https://www.brooklynvegan.com/feed/',
    'https://www.spin.com/feed/',
    'https://www.billboard.com/feed/',
    'https://www.rollingstone.com/music/music-news/feed/',
    'https://www.pastemagazine.com/music/rss/',
    # 'https://news.google.com/rss/search?q=music+industry+news&hl=en-US&gl=US&ceid=US:en',
]

GOOGLE_SHEET_NAME = 'InYourBones Daily Music News'
MAX_RESULTS = 100

# --- LOAD FILTERS ---
with open('filters.json', 'r', encoding='utf-8') as f:
    filter_config = json.load(f)

EXCLUDE_KEYWORDS = filter_config.get("excluded_keywords", [])

# --- SETUP GOOGLE SHEETS ---
scope = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/spreadsheets',
         'https://www.googleapis.com/auth/drive.file',
         'https://www.googleapis.com/auth/drive']

creds = ServiceAccountCredentials.from_json_keyfile_name('creds.json', scope)
gsheet = gspread.authorize(creds, http_client=BackOffHTTPClient)  # retries 429/5xx
spreadsheet = gsheet.open(GOOGLE_SHEET_NAME)

# --- HELPERS ---
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

def extract_image(entry):
    for key in ['media_content', 'media_thumbnail']:
        if key in entry:
            media = entry[key]
            if isinstance(media, list) and 'url' in media[0]:
                return media[0]['url']
            elif isinstance(media, dict) and 'url' in media:
                return media['url']

    if 'enclosures' in entry and entry.enclosures:
        for enclosure in entry.enclosures:
            if 'image' in enclosure.type or 'jpg' in enclosure.href:
                return enclosure.href

    try:
        response = requests.get(entry.link, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            return og_image["content"]
        twitter_image = soup.find("meta", attrs={"name": "twitter:image"})
        if twitter_image and twitter_image.get("content"):
            return twitter_image["content"]
    except Exception as e:
        print(f"Failed to fetch image from {entry.link}: {e}")

    return None

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
                    image_url = extract_image(entry)
                    results.append((entry.published_parsed[:6], {
                        'title': title,
                        'link': entry.link,
                        'source': feed.feed.title,
                        'published': entry.published,
                        'image': image_url
                    }))
    print(f"Fetched {len(results)} articles from yesterday (PST) (deduplicated by title)")
    # Sort on the parsed UTC time; the raw 'published' strings ("Wed, 21 Oct...") don't sort chronologically
    results.sort(key=lambda r: r[0], reverse=True)
    return [article for _, article in results]

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
        worksheet = spreadsheet.add_worksheet(title=sheet_tab, rows="1000", cols="5")

    all_values = worksheet.get_all_values()
    print(f"Current sheet row count: {len(all_values)}")

    # Set or update headers
    default_headers = ['Title', 'Link', 'Source', 'Published', 'Image']
    if all_values:
        headers = all_values[0]
        if 'Image' not in headers:
            headers.append('Image')
    else:
        headers = default_headers

    filtered_values = []
    removed_count = 0

    for row in all_values[1:]:
        if row and len(row) >= 4:
            try:
                parsed_date = parser.parse(row[3]).astimezone(pacific).date()
                if parsed_date.strftime('%Y-%m-%d') != date_str:
                    while len(row) < len(headers):
                        row.append('')
                    filtered_values.append(row)
                else:
                    removed_count += 1
            except Exception as e:
                print(f"Error parsing row date: {row[3]} -> {e}")
                while len(row) < len(headers):
                    row.append('')
                filtered_values.append(row)
    print(f"Removed {removed_count} rows from {date_str}")

    new_rows = [[a['title'], a['link'], a['source'], a['published'], a.get('image', '')] for a in articles[:MAX_RESULTS]]
    unique_rows = []
    seen = set()
    for row in new_rows:
        if row[0] not in seen:
            seen.add(row[0])
            unique_rows.append(row)

    print(f"Appending {len(unique_rows)} new unique rows")
    final_data = [headers] + filtered_values + unique_rows
    # Write before clearing leftover rows so a failed API call can't leave the tab empty
    worksheet.update(values=final_data, range_name='A1')
    if len(all_values) > len(final_data):
        worksheet.batch_clear([f"A{len(final_data) + 1}:Z{len(all_values)}"])

# --- BACKFILL A PAST DAY ---
def load_day_from_sheet(date_str):
    """Articles for a past news day, read back from the monthly tab instead of RSS
    (feeds only keep recent items)."""
    pacific = pytz.timezone("America/Los_Angeles")
    day = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    # The daily run saves yesterday's articles to the tab for the month it runs in
    sheet_tab = (day + datetime.timedelta(days=1)).strftime('%B %Y')
    found = []
    for row in spreadsheet.worksheet(sheet_tab).get_all_values()[1:]:
        if len(row) < 4:
            continue
        try:
            published = parser.parse(row[3]).astimezone(pacific)
        except Exception:
            continue
        if published.date() == day:
            found.append((published, {
                'title': row[0],
                'link': row[1],
                'source': row[2],
                'published': row[3],
                'image': row[4] if len(row) > 4 else ''
            }))
    found.sort(key=lambda r: r[0], reverse=True)
    print(f"Loaded {len(found)} articles for {date_str} from sheet tab '{sheet_tab}'")
    if not found:
        sys.exit(f"❌ No articles found for {date_str}; nothing to backfill.")
    return [article for _, article in found]

# --- MAIN ---
if __name__ == '__main__':
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--date", help="Backfill a past news day (YYYY-MM-DD, Pacific) from the monthly sheet")
    args = arg_parser.parse_args()

    if args.date:
        articles = load_day_from_sheet(args.date)
    else:
        articles = fetch_recent_articles()
        update_monthly_sheet(articles)
        print(f"Posted {min(len(articles), MAX_RESULTS)} unique articles to current month's sheet.")

    with open('latest_articles.json', 'w', encoding='utf-8') as f:
        json.dump(articles[:MAX_RESULTS], f, indent=2)
