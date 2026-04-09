import { NextResponse } from 'next/server';

/**
 * [V8.9.9] 시뮬레이터 통합 통계 API (Remote DB Version)
 * GitHub Raw URL에서 시뮬레이터 상태를 가져와 통합 통계를 산출합니다.
 */
export async function GET() {
    try {
        const GITHUB_BASE = 'https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data';
        const types = [
            { id: 'sim1', file: 'sim_standard_state.json' },
            { id: 'sim2', file: 'sim_conservative_state.json' },
            { id: 'sim3', file: 'sim_aggressive_state.json' }
        ];

        const results: any = {};
        
        await Promise.all(types.map(async (type) => {
            try {
                const res = await fetch(`${GITHUB_BASE}/${type.file}`, { cache: 'no-store' });
                if (!res.ok) throw new Error(`Fetch failed for ${type.file}`);
                
                const state = await res.json();
                
                // 간단한 통계 산출 (평가 금액 합산)
                // 상태 데이터에 이미 total_asset 등이 포함되어 있다고 가정하거나, 
                // 포트폴리오 정보를 기반으로 계산
                let portfolioValue = 0;
                if (state.portfolio) {
                    Object.values(state.portfolio).forEach((item: any) => {
                        // Python 시뮬레이터가 저장한 마지막 가격 혹은 평균 단가 사용
                        const price = item.current_price || item.avg_price || 0;
                        const qty = item.quantity || item.qty || 0;
                        portfolioValue += price * qty;
                    });
                }

                const totalAsset = (state.cash || 0) + portfolioValue;
                const initialCash = state.initial_cash || 3000000;
                const profit = totalAsset - initialCash;
                const returnRate = (profit / initialCash) * 100;

                results[type.id] = {
                    raw: {
                        cash: state.cash,
                        portfolio_value: portfolioValue,
                        total_asset: totalAsset,
                        profit: profit,
                        profit_rate: returnRate,
                        current_prices: Object.fromEntries(
                            Object.entries(state.portfolio || {}).map(([c, p]: [string, any]) => [c, p.current_price || p.avg_price || 0])
                        )
                    },
                    portfolio: state.portfolio || {}
                };
            } catch (err) {
                console.error(`[StatsAPI] Error processing ${type.id}:`, err);
                results[type.id] = { raw: {}, portfolio: {} };
            }
        }));

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
