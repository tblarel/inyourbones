// src/app/api/save/route.ts

import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { google } from 'googleapis';
import { JWT } from 'google-auth-library';

export async function POST(req: NextRequest) {
  try {
    const { articles } = await req.json();
    if (!Array.isArray(articles)) throw new Error("Invalid data format: expected an array");
    console.log("Received articles:", articles);
    console.log("✅ Received in API route:", articles);

    // --- Save to local file (root and public copies) ---
    const jsonString = JSON.stringify(articles, null, 2);
    try {
      const rootPath = path.join(process.cwd(), 'top_articles_with_captions.json');
      const publicPath = path.join(process.cwd(), 'public', 'top_articles_with_captions.json');

      fs.writeFileSync(rootPath, jsonString);
      fs.writeFileSync(publicPath, jsonString);

      console.log("✅ JSON written to both root and public folders.");
    } catch (err) {
      console.error("❌ Failed to write local JSON:", err);
      return NextResponse.json({ success: false, error: 'Failed to save JSON locally' }, { status: 500 });
    }

    // --- Update Google Sheet ---
    try {
      const credsB64 = process.env.CREDS_B64;
      const sheetId = process.env.SHEET_ID;

      if (!credsB64 || !sheetId) throw new Error("Missing Google credentials or Sheet ID");

      const creds = JSON.parse(Buffer.from(credsB64, 'base64').toString('utf8'));
      const jwt = new JWT({
        email: creds.client_email,
        key: creds.private_key,
        scopes: [
          'https://www.googleapis.com/auth/spreadsheets',
          'https://www.googleapis.com/auth/drive'
        ]
      });

      const sheets = google.sheets({ version: 'v4', auth: jwt });

      const now = new Date();
      const monthName = now.toLocaleString('en-US', { month: 'long', year: 'numeric' });
      const sheetTab = `${monthName} (selects)`;

      const values = articles.map(a => [
        a.title || '',
        a.link || '',
        a.source || '',
        a.published || '',
        a.caption || '',
        a.approved ? '✅' : '❌'
      ]);

      await sheets.spreadsheets.values.update({
        spreadsheetId: sheetId,
        range: `${sheetTab}!A2`,
        valueInputOption: 'RAW',
        requestBody: { values }
      });

      console.log(`✅ Google Sheet updated in tab: ${sheetTab}`);
    } catch (err) {
      console.warn("⚠️ Skipped Sheets update due to error:", err);
    }

    return NextResponse.json({ success: true });
  } catch (err) {
    console.error("❌ API handler error:", err);
    return NextResponse.json({ success: false, error: 'Server error' }, { status: 500 });
  }
}
