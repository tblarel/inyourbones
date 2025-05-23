// /src/app/api/dispatch/route.ts
import { NextRequest, NextResponse } from 'next/server';

export async function POST(req: NextRequest) {
  const body = await req.json();

  const res = await fetch('https://api.github.com/repos/tblarel/inyourbones/actions/workflows/rss_regen.yml/dispatches', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${process.env.GITHUB_PAT}`,
      'Accept': 'application/vnd.github+json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ ref: 'main' }),
  });

  if (!res.ok) {
    const errorText = await res.text();
    return new NextResponse(errorText, { status: res.status });
  }

  return new NextResponse('Dispatched', { status: 200 });
}
