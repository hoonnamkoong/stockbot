import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
    return NextResponse.json({
        status: 'ok',
        version: '1.0.1',
        timestamp: new Date().toISOString(),
        features: {
            acceptsX59Triggers: true,
            weekendCheck: true,
            holidayCheck: true,
            scrapingHours: [10, 13, 15]
        }
    });
}
