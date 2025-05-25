# rss_writer.py

import os
import json
import datetime
import base64
import sys
from xml.etree.ElementTree import Element, SubElement, ElementTree
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dateutil import parser as date_parser

SITE_URL = 'https://inyourbones.live/'
FEED_TITLE = 'InYourBones Daily Music News'
FEED_DESCRIPTION = 'Top 5 daily music stories handpicked by InYourBones'

def _get_output_file(loadAll):
    return 'feed_all.xml' if loadAll else 'feed.xml'

def load_articles_from_sheets(loadAll=False):
    print(f"🛠️  Running with loadAll={loadAll}")
    today = datetime.datetime.now().date()
    print(f"📅 Today: {today}")

    creds_b64 = os.getenv("CREDS_B64")
    sheet_id = os.getenv("SHEET_ID")

    if not creds_b64 or not sheet_id:
        raise RuntimeError("Missing CREDS_B64 or SHEET_ID env vars")

    creds_json = base64.b64decode(creds_b64).decode("utf-8")
    creds = service_account.Credentials.from_service_account_info(json.loads(creds_json))
    service = build('sheets', 'v4', credentials=creds)

    tab_name = datetime.datetime.now().strftime('%B %Y (selects)')

    result = service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range=f"{tab_name}!A2:F"
    ).execute()

    rows = result.get('values', [])
    articles = []
    seen_links = set()
    seen_titles = set()

    for row in rows:
        if len(row) < 5:
            print(f"⚠️ Skipping incomplete row: {row}")
            continue

        try:
            published_date = date_parser.parse(row[3])
        except Exception as e:
            print(f"⚠️ Failed to parse date '{row[3]}' in row: {row} — {e}")
            continue

        if not loadAll:
            approval = row[5] if len(row) >= 6 else ''
            if approval == '❌':
                continue
            if (today - published_date.date()).days > 1:
                print(f"⏭ Skipping row not from today or yesterday: {published_date.date()}")
                continue

        # Deduplication
        if row[1] in seen_links or row[0] in seen_titles:
            continue
        seen_links.add(row[1])
        seen_titles.add(row[0])

        print(f"✅ Row accepted: {row[0]} ({published_date.isoformat()})")

        articles.append({
            "title": row[0],
            "link": row[1],
            "source": row[2],
            "published": row[3],
            "caption": row[4],
            "published_dt": published_date
        })

    articles = sorted(articles, key=lambda a: a["published_dt"], reverse=True)[:5]
    print("\n📝 Final sorted article titles:")
    for a in articles:
        print(f" - {a['title']} @ {a['published_dt']}")

    return articles

def generate_rss(loadAll=False):
    print(f"🛠️  Running generateRSS with loadAll={loadAll}")
    print(f"📅 Today: {datetime.datetime.now().date()}")

    try:
        articles = load_articles_from_sheets(loadAll=loadAll)
    except Exception as e:
        print(f"❌ Error loading from Google Sheets: {e}")
        return

    rss = Element('rss', version='2.0')
    channel = SubElement(rss, 'channel')

    SubElement(channel, 'title').text = FEED_TITLE
    SubElement(channel, 'link').text = SITE_URL
    SubElement(channel, 'description').text = FEED_DESCRIPTION
    SubElement(channel, 'lastBuildDate').text = datetime.datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S +0000')

    for article in articles:
        item = SubElement(channel, 'item')
        SubElement(item, 'title').text = article.get('title', '')
        SubElement(item, 'link').text = article.get('link', '')
        SubElement(item, 'guid').text = article.get('link', '')
        SubElement(item, 'description').text = article.get('caption', '')
        SubElement(item, 'pubDate').text = article.get('published', '')

    output_file = _get_output_file(loadAll)
    tree = ElementTree(rss)
    tree.write(output_file, encoding='utf-8', xml_declaration=True)
    print(f"✅ RSS feed written to {output_file} using {len(articles)} item(s)")

if __name__ == '__main__':
    import argparse
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--loadAll", action="store_true", help="Load all articles")
    args = arg_parser.parse_args()
    generate_rss(loadAll=args.loadAll)
