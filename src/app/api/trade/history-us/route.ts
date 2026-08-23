import { NextResponse } from 'next/server';
import { US_SIM_REGISTRY } from '@/lib/us-sim-registry.generated';
import { createBucketCache, dbDataUrl } from '@/lib/db-data';
import { parseSimHistoryCsv } from '@/lib/trade-history-csv';

export const dynamic = 'force-dynamic';

async function fetchSimHistory(fileInfo: { type: string; name: string }) {
    try {
        const res = await fetch(dbDataUrl(fileInfo.name), { cache: 'no-store' });
        if (!res.ok) return [];
        return parseSimHistoryCsv(await res.text(), fileInfo.type);
    } catch (err) {
        console.error(`[HistoryAPI-US] Error fetching ${fileInfo.name}:`, err);
        return [];
    }
}

const loadUsSimHistories = createBucketCache(async () => {
    const simFiles = US_SIM_REGISTRY.map((s) => ({ type: s.id, name: s.csvFile }));
    const histories = await Promise.all(simFiles.map(fetchSimHistory));
    return histories.flat();
});

export async function GET() {
    try {
        const data = await loadUsSimHistories();
        data.sort((a: any, b: any) => {
            const timeA = new Date(a.time).getTime();
            const timeB = new Date(b.time).getTime();
            return isNaN(timeB) || isNaN(timeA) ? 0 : timeB - timeA;
        });
        return NextResponse.json({ success: true, count: data.length, data });
    } catch (error: any) {
        return NextResponse.json(
            { success: false, error: 'Failed to fetch US trade history', details: error.message },
            { status: 500 }
        );
    }
}
