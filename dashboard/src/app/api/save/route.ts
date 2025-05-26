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
    console.log("✅ Received in API route:", articles);

    // Save to local and public folders
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

    // Update Google Sheet
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

      // Get existing rows
      const existing = await sheets.spreadsheets.values.get({
        spreadsheetId: sheetId,
        range: `${sheetTab}!A2:F`
      });
      const existingRows = existing.data.values || [];

      // Build updated rows
      const updatedRows = existingRows.map(row => {
        const match = articles.find(a => a.link === row[1]);
        if (match) {
          return [
            match.title || '',
            match.link || '',
            match.source || '',
            match.published || '',
            match.caption || '',
            match.image || '',
            match.approval === true ? '✅' : match.approval === false ? '❌' : ''
          ];
        }
        return row;
      });

      await sheets.spreadsheets.values.update({
        spreadsheetId: sheetId,
        range: `${sheetTab}!A2`,
        valueInputOption: 'RAW',
        requestBody: { values: updatedRows }
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
