// src/app/api/load/route.ts

import { google } from 'googleapis';
import { JWT } from 'google-auth-library';
import { NextRequest, NextResponse } from 'next/server';

export async function GET(req: NextRequest) {
  try {
    const credsB64 = process.env.CREDS_B64;
    const sheetId = process.env.SHEET_ID;

    if (!credsB64 || !sheetId) {
      throw new Error("Missing Google credentials or Sheet ID");
    }

    const creds = JSON.parse(Buffer.from(credsB64, 'base64').toString('utf8'));
    const jwt = new JWT({
      email: creds.client_email,
      key: creds.private_key,
      scopes: [
        'https://www.googleapis.com/auth/spreadsheets.readonly',
        'https://www.googleapis.com/auth/drive.readonly'
      ]
    });

    const sheets = google.sheets({ version: 'v4', auth: jwt });

    const now = new Date();
    const sheetTab = now.toLocaleString('en-US', { month: 'long', year: 'numeric' }) + ' (selects)';

    const res = await sheets.spreadsheets.values.get({
      spreadsheetId: sheetId,
      range: `${sheetTab}!A2:F`,
    });

    const rows = res.data.values || [];
    const yesterday = new Date(Date.now() - 86400000);
    const ymd = yesterday.toISOString().slice(0, 10);

    const articles = rows
      .map(row => ({
      title: row[0] || '',
      link: row[1] || '',
      source: row[2] || '',
      published: row[3] || '',
      caption: row[4] || '',
      approval: row[5] ?? null,
      }))
      .filter(a => a.published);

    const uniqueArticlesMap = new Map<string, typeof articles[0]>();
    for (const article of articles.sort((a, b) =>
      new Date(b.published).getTime() - new Date(a.published).getTime()
    )) {
      if (!uniqueArticlesMap.has(article.link)) {
      uniqueArticlesMap.set(article.link, article);
      }
    }

    const recent5UniqueArticles = Array.from(uniqueArticlesMap.values()).slice(0, 5);

    return NextResponse.json(recent5UniqueArticles);
  } catch (err) {
    console.error("❌ Error loading from Google Sheets:", err);
    return NextResponse.json({ success: false, error: 'Failed to load data' }, { status: 500 });
  }
}
