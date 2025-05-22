# daily_sms_recap.py

import os
import json
import datetime
from dotenv import load_dotenv
from twilio.rest import Client

# --- SETUP ---
load_dotenv()
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")  # Use this instead of Messaging Service SID
TO_NUMBER = os.getenv("TWILIO_TO_NUMBER")

INPUT_FILE = 'top_articles_with_captions.json'

# --- FORMAT MESSAGE ---
def format_sms(articles):
    today = datetime.datetime.now().strftime("%A, %B %d")
    lines = [f"📰 InYourBones Daily Recap — {today}\nReply 'NO 2' to veto #2, etc.\n"]

    for i, article in enumerate(articles, 1):
        title = article.get("title", "")
        caption = article.get("caption", "")
        msg = f"{i}. {title}\n{caption}"
        # If message is too long, truncate caption to fit within 1 SMS (160 chars total budget)
        if len(msg) > 153:
            max_caption_len = 153 - len(f"{i}. {title}\n") - 3
            caption = caption[:max_caption_len].rstrip() + "..."
            msg = f"{i}. {title}\n{caption}"
        lines.append(msg)

    return lines

# --- SEND MESSAGE (SIMULATED) ---
def send_sms(messages):
    try:
        # client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        for i, body in enumerate(messages):
            print("\n--- SMS Message #{0} ---\n{1}\n".format(i + 1, body))
            # message = client.messages.create(
            #     from_=TWILIO_FROM_NUMBER,
            #     to=TO_NUMBER,
            #     body=body
            # )
            # print(f"✅ Sent SMS {i+1}: SID {message.sid}")
    except Exception as e:
        print(f"❌ Error sending SMS: {e}")

# --- MAIN ---
def main():
    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            articles = json.load(f)
    except FileNotFoundError:
        print("❌ No top_articles_with_captions.json file found.")
        return

    messages = format_sms(articles)
    send_sms(messages)

if __name__ == '__main__':
    main()
