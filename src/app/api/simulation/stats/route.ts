import { NextResponse } from 'next/server';
import { SIM_REGISTRY, ANALYZERS } from '@/lib/sim-registry.generated';
import { createBucketCache, dbDataUrl } from '@/lib/db-data';

export const dynamic = 'force-dynamic';

/**
 * [V8.9.9] 시뮬레이터 통합 통계 API (Remote DB Version)
 * GitHub Raw URL에서 시뮬레이터 상태를 가져와 통합 통계를 산출합니다.
 *
 * 한 번 계산에 GitHub raw 13회(심 12 + 리베로). 전부 db-data의 파일이고 생산자는
 * 10분마다 도는 파이프라인이라, 같은 신선도 버킷 안에서는 한 번만 계산한다
 * (src/lib/db-data.ts). 재로드·동시 접속이 오리진을 다시 치지 않는다.
 */
const loadStats = createBucketCache(async () => {
    // 페이퍼 관찰 단계(tradeable: false)도 포함한다 — 실전 승격 전 성과를 축적한다
    const types = SIM_REGISTRY.map((s) => ({ id: s.uiKey, file: s.stateFile }));

    const results: any = {};

    await Promise.all(types.map(async (type) => {
        try {
            const res = await fetch(dbDataUrl(type.file), { cache: 'no-store' });
            if (!res.ok) throw new Error(`Fetch failed for ${type.file}`);
            
            const state = await res.json();
            
            // 항상 live state.cash 기준으로 계산 (raw_stats.cash는 buy() 직후 stale 가능)
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
            const initialCash = state.initial_cash || 3000000;
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
            console.error(`[StatsAPI] Error processing ${type.id}:`, err);
            results[type.id] = { raw: {}, portfolio: {} };
        }
    }));

    // 리베로: 매매하지 않는 시장 국면 분석기 → 통계가 아닌 국면 정보를 별도 첨부.
    // 응답 형태가 이 심에만 있는 필드(current_regime 등)라 목록화하지 않고 id로 짚는다.
    const libero = ANALYZERS.find((a) => a.id === 'sim0_libero');
    try {
        if (!libero) throw new Error('매니페스트에 sim0_libero 분석기가 없다');
        const res = await fetch(dbDataUrl(libero.stateFile), { cache: 'no-store' });
        if (res.ok) {
            const s = await res.json();
            results.libero = {
                current_regime: s.current_regime ?? null,
                bull_score: s.bull_score ?? null,
                regime_confidence: s.regime_confidence ?? null,
                recommended_sims: s.recommended_sims ?? [],
                metrics: s.metrics ?? {},
                last_run: s.last_run ?? null,
                regime_history: s.regime_history ?? [],
                daily_regime_log: s.daily_regime_log ?? [],
            };
        } else {
            results.libero = null;
        }
    } catch (err) {
        console.error('[StatsAPI] Error processing libero:', err);
        results.libero = null;
    }

    // 요청 시각이 아니라 이 계산이 돈 시각이다 — 화면에 뜨는 값이 언제 것인지 말해준다.
    results["last_updated"] = new Date().toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' });
    return results;
});

export async function GET() {
    try {
        return NextResponse.json(await loadStats());
    } catch (error: any) {
        console.error('[Simulation API] Error fetching stats:', error);
        return NextResponse.json(
            { error: 'Failed to fetch simulation stats', details: error.message },
            { status: 500 }
        );
    }
}
