import { NextRequest, NextResponse } from 'next/server';

/**
 * [V8.9.9] Trading History API (Remote DB Version)
 * Fetches CSV log files from GitHub Raw and returns them as structured JSON.
 */

export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
    try {
        const GITHUB_BASE = 'https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data';
        
        // 1. Files to search
        const fileInfos = [
            { type: 'real', name: 'trade_history_real.csv' },
            { type: 'sim_original', name: 'trade_history_sim_original.csv' },
            { type: 'sim_conservative', name: 'trade_history_sim_conservative.csv' },
            { type: 'sim_aggressive', name: 'trade_history_sim_aggressive.csv' },
            { type: 'sim_conviction', name: 'trade_history_sim_conviction.csv' }
        ];

        let allHistory: any[] = [];

        await Promise.all(fileInfos.map(async (fileInfo) => {
            try {
                const res = await fetch(`${GITHUB_BASE}/${fileInfo.name}`, { cache: 'no-store' });
                if (!res.ok) return;

                const content = await res.text();
                const lines = content.split('\n').filter(line => line.trim().length > 0);
                
                if (lines.length > 1) { // Header exists
                    const headers = lines[0].split(',').map(h => h.trim().replace(/^"|"$/g, ''));
                    
                    for (let i = 1; i < lines.length; i++) {
                        const values = lines[i].split(',').map(v => v.trim().replace(/^"|"$/g, ''));
                        if (values.length < headers.length) continue;

                        const entry: any = { type: fileInfo.type };
                        headers.forEach((h, idx) => {
                            if (h === 'timestamp') entry.time = values[idx];
                            else if (h === 'symbol') entry.symbol = values[idx];
                            else if (h === 'action') entry.action = values[idx].toUpperCase();
                            else if (h === 'price') entry.price = values[idx];
                            else if (h === 'quantity') entry.qty = values[idx];
                            else if (h === 'total_amount') entry.amount = values[idx];
                            else if (h === 'reason') entry.reason = values[idx];
                        });
                        
                        if (!entry.amount && entry.price && entry.qty) {
                            const p = parseInt(entry.price.replace(/,/g, ''));
                            const q = parseInt(entry.qty);
                            if (!isNaN(p) && !isNaN(q)) {
                                entry.amount = (p * q).toLocaleString();
                            }
                        }
                        allHistory.push(entry);
                    }
                }
            } catch (err) {
                console.error(`[HistoryAPI] Error fetching ${fileInfo.name}:`, err);
            }
        }));

        // Sort by timestamp descending
        allHistory.sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime());

        return NextResponse.json({ 
            success: true, 
            count: allHistory.length,
            data: allHistory 
        });

    } catch (error: any) {
        console.error("[API History Error]", error);
        return NextResponse.json({ success: false, error: error.message }, { status: 500 });
    }
}
