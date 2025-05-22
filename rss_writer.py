# rss_writer.py

import datetime
import json
from xml.etree.ElementTree import Element, SubElement, ElementTree

INPUT_FILE = 'top_articles_with_captions.json'
OUTPUT_FILE = 'feed.xml'
SITE_URL = 'https://inyourbones.live/'
FEED_TITLE = 'InYourBones Daily Music News'
FEED_DESCRIPTION = 'Top 5 daily music stories handpicked by InYourBones'

# --- MAIN ---
def generate_rss():
    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            articles = json.load(f)
    except FileNotFoundError:
        print("❌ No top_articles_with_captions.json file found.")
        return

    # Root RSS structure
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
    print(f"✅ RSS feed written to {OUTPUT_FILE}")

if __name__ == '__main__':
    generate_rss()
