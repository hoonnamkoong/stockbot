import { NextResponse } from 'next/server';

export async function GET() {
    return NextResponse.json({
        version: "v2026.01.06-16:47",
        timestamp: new Date().toISOString(),
        commit: "1bf0338",
        message: "If you see this, new deployment is LIVE!"
    });
}
