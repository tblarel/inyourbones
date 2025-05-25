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
        range=f"{tab_name}!A2:G"
    ).execute()

    rows = result.get('values', [])
    articles = []
    seen_links = set()
    seen_titles = set()

    for row_num, row in enumerate(rows, start=2):
        if len(row) < 4:
            print(f"⚠️ Skipping short row (less than 4 cols) at row {row_num}: {row}")
            continue

        try:
            title = row[0]
            link = row[1]
            source = row[2]
            published = row[3]
            caption = row[4] if len(row) > 4 else ''
            image = row[5] if len(row) > 5 else ''
            approval = row[6] if len(row) > 6 else ''

            published_date = date_parser.parse(published)
        except Exception as e:
            print(f"⚠️ Error processing row {row_num}: {row} — {e}")
            continue

        if approval == '❌':
            print(f"🚫 Skipping disapproved row {row_num}: {title}")
            continue

        if not loadAll and (today - published_date.date()).days > 1:
            print(f"⏭ Skipping row not from today or yesterday ({published_date.date()}) at row {row_num}")
            continue

        # Deduplication
        if link in seen_links or title in seen_titles:
            print(f"🔁 Duplicate skipped at row {row_num}: {title}")
            continue
        seen_links.add(link)
        seen_titles.add(title)

        print(f"✅ Row accepted at row {row_num}: {title} ({published_date.isoformat()})")

        articles.append({
            "title": title,
            "link": link,
            "source": source,
            "published": published,
            "caption": caption,
            "image": image if loadAll else '',
            "published_dt": published_date
        })

    articles = sorted(articles, key=lambda a: a["published_dt"], reverse=True)
    if not loadAll:
        articles = articles[:5]

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

    rss = Element('rss', {
        'version': '2.0',
        'xmlns:media': 'http://search.yahoo.com/mrss/'
    })
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

        # ✅ Add image if available
        image_url = article.get('image')
        if image_url:
            SubElement(item, 'media:content', {
                'url': image_url,
                'medium': 'image'
            })

    output_file = _get_output_file(loadAll)
    tree = ElementTree(rss)
    tree.write(output_file, encoding='utf-8', xml_declaration=True)
    print(f"\n✅ RSS feed written to {output_file} using {len(articles)} item(s)")


if __name__ == '__main__':
    import argparse
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--loadAll", action="store_true", help="Load all articles")
    args = arg_parser.parse_args()
    generate_rss(loadAll=args.loadAll)
