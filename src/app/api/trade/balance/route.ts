import { NextResponse } from 'next/server';
import { getBalance } from '@/lib/kis';
import path from 'path';
import fs from 'fs/promises';

export const dynamic = 'force-dynamic';

export async function GET() {
    console.log('[Balance API] Request received');
    try {
        const balance = await getBalance();
        console.log('[Balance API] getBalance returned:', balance ? 'data' : 'null');

        if (balance) {
            // Merge Local History
            try {
                const historyPath = path.join(process.cwd(), 'data', 'order_history.json');
                const historyData = await fs.readFile(historyPath, 'utf-8');
                const history = JSON.parse(historyData);

                // Inject last_buy_date
                balance.holdings = balance.holdings.map(h => ({
                    ...h,
                    last_buy_date: history[h.code] || '-'
                }));
                console.log('[Balance API] History merged, returning data');
            } catch (e) {
                console.log("[Balance API] No history found, continuing without it");
            }

            return NextResponse.json(balance);
        } else {
            console.error('[Balance API] getBalance returned null');
            // Check logs for details, but return a hint
            return NextResponse.json({ error: 'Failed to fetch balance from KIS (getBalance returned null). Check server logs for Token/API errors.' }, { status: 500 });
        }
    } catch (error: any) {
        console.error('[Balance API] Exception:', error.message);
        return NextResponse.json({
            error: `Internal Error: ${error.message}`,
            details: error.stack,
            envCheck: {
                hasKey: !!process.env.KIS_APP_KEY,
                hasSecret: !!process.env.KIS_APP_SECRET,
                hasAcc: !!process.env.KIS_ACCOUNT_NO,
                baseUrl: process.env.KIS_BASE_URL
            }
        }, { status: 500 });
    }
}
