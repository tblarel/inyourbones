import os
import re
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
    'https://www.nme.com/news/music/feed',  # old /news/rss URL now serves an HTML page
    # 'https://www.brooklynvegan.com/feed/',  # stale since 2026-10-06
    'https://www.spin.com/feed/',
    'https://www.billboard.com/feed/',
    'https://www.rollingstone.com/music/music-news/feed/',
    # 'https://www.pastemagazine.com/music/rss/',  # serves an HTML page since ~Oct 2026
    # 'https://news.google.com/rss/search?q=music+industry+news&hl=en-US&gl=US&ceid=US:en',
]

GOOGLE_SHEET_NAME = 'InYourBones Daily Music News'
MAX_RESULTS = 300
MAX_FEED_PAGES = 150  # Billboard holds ~2h of posts per page: ~15 pages for a daily run, ~100 to backfill a week

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
def published_date_pst(published_dt):
    pacific = pytz.timezone("America/Los_Angeles")
    return datetime.datetime(*published_dt[:6], tzinfo=datetime.timezone.utc).astimezone(pacific).date()

def yesterday_pst():
    return (datetime.datetime.now(pytz.timezone("America/Los_Angeles")) - datetime.timedelta(days=1)).date()

# Whole words only: plain substring matching dropped "Awards" (war), "Miranda" (iran), "Stewart" (war)...
EXCLUDE_PATTERN = re.compile(r"\b(?:" + "|".join(re.escape(k) for k in EXCLUDE_KEYWORDS) + r")\b")

# Sections that aren't news, e.g. Billboard's shopping and "how to watch" posts
EXCLUDE_LINK_PATHS = filter_config.get("excluded_link_paths", [])

def is_relevant(title, link=''):
    return not EXCLUDE_PATTERN.search(title.lower()) and not any(p in link for p in EXCLUDE_LINK_PATHS)

def fetch_feed(url, day):
    """Return (feed title, entries back to the start of `day` PST).
    Busy feeds only hold a few hours of posts per page, so by morning most of yesterday has
    rolled off page 1; walk back with WordPress's ?paged=N until a page reaches before `day`."""
    first = feedparser.parse(url)
    entries = list(first.entries)
    seen_links = {e.get('link') for e in entries}
    for page in range(2, MAX_FEED_PAGES + 1):
        dated = [e.published_parsed for e in entries if e.get('published_parsed')]
        if not dated or published_date_pst(min(dated)) < day:
            break
        new = [e for e in feedparser.parse(f"{url}?paged={page}").entries if e.get('link') not in seen_links]
        if not new:  # past the last page, or a feed that ignores ?paged
            break
        entries.extend(new)
        seen_links.update(e.get('link') for e in new)
    return first.feed.get('title', url), entries

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
def fetch_articles(day):
    results = []
    seen_titles = set()
    for url in RSS_FEEDS:
        source, entries = fetch_feed(url, day)
        for entry in entries:
            published = entry.get('published_parsed')
            if published and published_date_pst(published) == day and is_relevant(entry.title, entry.get('link', '')):
                title = entry.title.strip()
                if title not in seen_titles:
                    seen_titles.add(title)
                    image_url = extract_image(entry)
                    results.append((entry.published_parsed[:6], {
                        'title': title,
                        'link': entry.link,
                        'source': source,
                        'published': entry.published,
                        'image': image_url
                    }))
    print(f"Fetched {len(results)} articles from {day} (PST) (deduplicated by title)")
    # Sort on the parsed UTC time; the raw 'published' strings ("Wed, 21 Oct...") don't sort chronologically
    results.sort(key=lambda r: r[0], reverse=True)
    return [article for _, article in results]

def merge_articles(*groups):
    """Combine article lists newest first, dropping repeated titles or links."""
    merged, seen = [], set()
    for a in sorted((a for g in groups for a in g), key=lambda a: parser.parse(a['published']).timestamp(), reverse=True):
        if a['title'].strip() not in seen and a['link'].strip() not in seen:
            seen.update((a['title'].strip(), a['link'].strip()))
            merged.append(a)
    return merged

# --- WRITE TO MONTHLY SHEET ---
def update_monthly_sheet(articles, day):
    pacific = pytz.timezone("America/Los_Angeles")
    # The daily run saves yesterday's articles to the tab for the month it runs in
    sheet_tab = (day + datetime.timedelta(days=1)).strftime('%B %Y')
    date_str = day.strftime('%Y-%m-%d')
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
    if len(final_data) > worksheet.row_count:  # tabs start at 1000 rows; a month of full days needs more
        worksheet.add_rows(len(final_data) - worksheet.row_count)
    # Write before clearing leftover rows so a failed API call can't leave the tab empty
    worksheet.update(values=final_data, range_name='A1')
    if len(all_values) > len(final_data):
        worksheet.batch_clear([f"A{len(final_data) + 1}:Z{len(all_values)}"])

# --- BACKFILL A PAST DAY ---
def load_day_from_sheet(day):
    """Articles the original run saved for a past news day, read back from the monthly tab."""
    pacific = pytz.timezone("America/Los_Angeles")
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
    print(f"Loaded {len(found)} articles for {day} from sheet tab '{sheet_tab}'")
    return [article for _, article in found]

# --- MAIN ---
if __name__ == '__main__':
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--date", help="Backfill a past news day (YYYY-MM-DD, Pacific): re-pages the feeds "
                                           "(about a week back) and merges what the monthly sheet saved")
    args = arg_parser.parse_args()

    if args.date:
        day = datetime.datetime.strptime(args.date, '%Y-%m-%d').date()
        saved = [a for a in load_day_from_sheet(day) if is_relevant(a['title'], a['link'])]  # saved under older filters
        articles = merge_articles(fetch_articles(day), saved)
        if not articles:
            sys.exit(f"❌ No articles found for {args.date}; nothing to backfill.")
    else:
        day = yesterday_pst()
        articles = fetch_articles(day)
    update_monthly_sheet(articles, day)
    print(f"Posted {min(len(articles), MAX_RESULTS)} unique articles to the monthly sheet for {day}.")

    with open('latest_articles.json', 'w', encoding='utf-8') as f:
        json.dump(articles[:MAX_RESULTS], f, indent=2)
