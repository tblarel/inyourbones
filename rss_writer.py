# rss_writer.py

import os
import json
import datetime
from xml.etree.ElementTree import Element, SubElement, ElementTree
from google.oauth2 import service_account
from googleapiclient.discovery import build
import base64
from dateutil import parser

OUTPUT_FILE = 'feed.xml'
SITE_URL = 'https://inyourbones.live/'
FEED_TITLE = 'InYourBones Daily Music News'
FEED_DESCRIPTION = 'Top 5 daily music stories handpicked by InYourBones'

def load_articles_from_sheets():
    creds_b64 = os.getenv("CREDS_B64")
    sheet_id = os.getenv("SHEET_ID")

    if not creds_b64 or not sheet_id:
        raise RuntimeError("Missing CREDS_B64 or SHEET_ID env vars")

    creds_json = base64.b64decode(creds_b64).decode("utf-8")
    creds = service_account.Credentials.from_service_account_info(json.loads(creds_json))
    service = build('sheets', 'v4', credentials=creds)

    now = datetime.datetime.now()
    tab_name = now.strftime('%B %Y (selects)')

    result = service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range=f"{tab_name}!A2:F"
    ).execute()

    rows = result.get('values', [])
    articles = []

    for row in rows:
        approved = row[5]
        if approved == '❌':
            continue
        try:
            published_date = parser.parse(row[3])
        except Exception:
            published_date = datetime.datetime.min  # fallback if date parsing fails

        articles.append({
            "title": row[0],
            "link": row[1],
            "source": row[2],
            "published": row[3],
            "caption": row[4],
            "published_dt": published_date
        })

    # Sort by published date descending and return top 5
    return sorted(articles, key=lambda a: a["published_dt"], reverse=True)[:5]

def generate_rss():
    try:
        articles = load_articles_from_sheets()
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

    tree = ElementTree(rss)
    tree.write(OUTPUT_FILE, encoding='utf-8', xml_declaration=True)
    print(f"✅ RSS feed written to {OUTPUT_FILE} using {len(articles)} approved + sorted items")

if __name__ == '__main__':
    generate_rss()
