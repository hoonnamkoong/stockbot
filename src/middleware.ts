import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// Temporary Bypass for Vercel Build Debugging
// The import "next-auth/middleware" is failing on Vercel (Next.js 16 detection issue?)
export function middleware(request: NextRequest) {
    return NextResponse.next();
}

export const config = { matcher: ["/trade", "/trade/:path*", "/research", "/research/:path*"] }
