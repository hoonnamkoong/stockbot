import { NextResponse } from 'next/server';
import { US_SIM_REGISTRY } from '@/lib/us-sim-registry.generated';
import { createBucketCache, dbDataUrl } from '@/lib/db-data';

export const dynamic = 'force-dynamic';

const loadStats = createBucketCache(async () => {
    const types = US_SIM_REGISTRY.map((s) => ({ id: s.uiKey, file: s.stateFile }));
    const results: any = {};

    await Promise.all(types.map(async (type) => {
        try {
            const res = await fetch(dbDataUrl(type.file), { cache: 'no-store' });
            if (!res.ok) throw new Error(`Fetch failed for ${type.file}`);
            const state = await res.json();

            const currentPrices = state.raw_stats?.current_prices || {};
            let portfolioValue = 0;
            if (state.portfolio) {
                Object.entries(state.portfolio).forEach(([code, item]: [string, any]) => {
                    const price = currentPrices[code] || item.current_price || item.avg_price || 0;
                    const qty = item.quantity || item.qty || 0;
                    portfolioValue += price * qty;
                });
            }

            const liveCash = state.cash || 0;
            const totalAsset = liveCash + portfolioValue;
            const initialCash = state.initial_cash || 20000;
            const profit = totalAsset - initialCash;
            const returnRate = initialCash > 0 ? (profit / initialCash) * 100 : 0;

            results[type.id] = {
                raw: {
                    ...(state.raw_stats || {}),
                    cash: liveCash,
                    portfolio_value: portfolioValue,
                    total_asset: totalAsset,
                    profit,
                    profit_rate: returnRate,
                },
                normalized: state.normalized_stats || {},
                portfolio: state.portfolio || {}
            };
        } catch (err) {
            console.error(`[StatsAPI-US] Error processing ${type.id}:`, err);
            results[type.id] = { raw: {}, portfolio: {} };
        }
    }));

    results["last_updated"] = new Date().toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' });
    return results;
});

export async function GET() {
    try {
        return NextResponse.json(await loadStats());
    } catch (error: any) {
        console.error('[Simulation API US] Error fetching stats:', error);
        return NextResponse.json(
            { error: 'Failed to fetch simulation stats', details: error.message },
            { status: 500 }
        );
    }
}
