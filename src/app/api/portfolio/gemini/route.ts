import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

export async function GET() {
    try {
        const branch = 'db-data';
        const url = `https://raw.githubusercontent.com/hoonnamkoong/stockbot/${branch}/data/gemini_portfolio.json`;

        const res = await fetch(url, { cache: 'no-store' });

        if (!res.ok) {
            // File might not exist yet if scraper hasn't pushed
            return NextResponse.json({
                cash: 3000000,
                holdings: {},
                trade_log: [],
                last_update: ''
            });
        }

        const data = await res.json();
        return NextResponse.json(data);
    } catch (error) {
        console.error('Error reading gemini portfolio data from GitHub:', error);
        return NextResponse.json({ error: 'Failed to read gemini portfolio data' }, { status: 500 });
    }
}
