import { NextResponse } from 'next/server';
import { SIM_REGISTRY, ANALYZERS } from '@/lib/sim-registry.generated';

export const dynamic = 'force-dynamic';

/**
 * [V8.9.9] 시뮬레이터 통합 통계 API (Remote DB Version)
 * GitHub Raw URL에서 시뮬레이터 상태를 가져와 통합 통계를 산출합니다.
 */
export async function GET() {
    try {
        const GITHUB_BASE = 'https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data';
        // 페이퍼 관찰 단계(tradeable: false)도 포함한다 — 실전 승격 전 성과를 축적한다
        const types = SIM_REGISTRY.map((s) => ({ id: s.uiKey, file: s.stateFile }));

        const results: any = {};
        
        await Promise.all(types.map(async (type) => {
            try {
                const cacheBuster = Date.now();
                const res = await fetch(`${GITHUB_BASE}/${type.file}?t=${cacheBuster}`, { cache: 'no-store' });
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
            const res = await fetch(`${GITHUB_BASE}/${libero.stateFile}?t=${Date.now()}`, { cache: 'no-store' });
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

        results["last_updated"] = new Date().toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' });
        return NextResponse.json(results);
        
    } catch (error: any) {
        console.error('[Simulation API] Error fetching stats:', error);
        return NextResponse.json(
            { error: 'Failed to fetch simulation stats', details: error.message },
            { status: 500 }
        );
    }
}
