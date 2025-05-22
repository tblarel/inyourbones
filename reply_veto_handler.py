import os
import json
import re
from datetime import datetime
from dotenv import load_dotenv
from twilio.rest import Client
import gspread

# --- CONFIG ---
load_dotenv()
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")
TO_NUMBER = os.getenv("TWILIO_TO_NUMBER")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

JSON_PATH = "top_articles_with_captions.json"

# --- POLL & PARSE REPLIES ---
def fetch_latest_reply():
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    messages = client.messages.list(to=TWILIO_FROM_NUMBER, from_=TO_NUMBER, limit=10)

    for msg in messages:
        if "no" in msg.body.lower():
            print(f"📥 Found reply: {msg.body}")
            return msg.body.lower()
    print("⚠️ No valid veto message found.")
    return None


def extract_veto_indices(reply):
    return sorted(set(int(n) for n in re.findall(r"no\s*(\d+)", reply)))


def update_json_vetoes(indices):
    if not os.path.exists(JSON_PATH):
        print("❌ JSON file not found.")
        return []

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    for idx in indices:
        if 1 <= idx <= len(data):
            data[idx - 1]["vetoed"] = True
            print(f"🚫 Vetoed in JSON: {data[idx - 1]['title']}")

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        print("✅ Updated JSON with veto flags.")

    return indices


def update_sheet_vetoes(veto_indices):
    gc = gspread.service_account(filename=GOOGLE_CREDENTIALS)
    sheet = gc.open(GOOGLE_SHEET_NAME)
    today_str = datetime.now().strftime("%B %Y")  # e.g., "May 2025"

    try:
        worksheet = sheet.worksheet(f"{today_str} (selects)")
    except gspread.WorksheetNotFound:
        print("❌ Worksheet for selects not found.")
        return

    rows = worksheet.get_all_values()
    headers = rows[0]

    if "Approval" not in headers:
        worksheet.update_cell(1, len(headers) + 1, "Approval")
        headers.append("Approval")

    for i, row in enumerate(rows[1:], start=2):  # skip header
        if i - 1 in veto_indices:
            worksheet.update_cell(i, len(headers), "🚫 Vetoed")
            print(f"🚫 Vetoed in sheet: Row {i}")
        else:
            worksheet.update_cell(i, len(headers), "✅ Approved")


# --- MAIN ---
def main():
    reply = fetch_latest_reply()
    if reply:
        veto_indices = extract_veto_indices(reply)
        if veto_indices:
            updated = update_json_vetoes(veto_indices)
            update_sheet_vetoes(updated)
        else:
            print("⚠️ No valid veto indices found in reply.")


if __name__ == "__main__":
    main()
