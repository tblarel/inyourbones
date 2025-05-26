// src/app/api/dispatch/route.ts
import { NextRequest, NextResponse } from 'next/server';

// export async function POST() {
//   const res = await fetch('https://api.github.com/repos/tblarel/inyourbones/actions/workflows/rss_regen.yml/dispatches', {
//     method: 'POST',
//     headers: {
//       'Authorization': `Bearer ${process.env.GITHUB_PAT}`,
//       'Accept': 'application/vnd.github+json',
//       'Content-Type': 'application/json',
//     },
//     body: JSON.stringify({ ref: 'main' }),
//   });

//   if (!res.ok) {
//     const errorText = await res.text();
//     return new NextResponse(errorText, { status: res.status });
//   }

//   return new NextResponse('Dispatched', { status: 200 });
// }


//   const res = await fetch('https://api.github.com/repos/tblarel/inyourbones/actions/workflows/rss_regen.yml/dispatches', {
//     method: 'POST',
//     headers: {
//         Authorization: '',
//         Accept: 'application/vnd.github+json',
//         'Content-Type': 'application/json',
//     },
//     body: JSON.stringify({ ref: 'main' }),
//     });


export async function POST(req: NextRequest) {
  console.log("Dispatch route reached");
  if (!process.env.GITHUB_PAT) {
    return new NextResponse('GITHUB_PAT not set', { status: 500 });
  }
  const res = await fetch('https://api.github.com/repos/tblarel/inyourbones/actions/workflows/rss-regen.yml/dispatches', {
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
  // return new NextResponse(`✅ POST route is working received req data ${req.body}!`, { status: 200 });
}

// export async function GET() {
//   return new NextResponse('Dispatch route reachable');
// }