import { NextResponse } from 'next/server';
import { SIM_INITIAL_CASH } from '@/lib/sim-registry.generated';

/**
 * [V8.9.9] 시뮬레이터 상태 동기화 API (Remote DB Version)
 * GitHub Raw 디렉토리의 시뮬레이터 상태 파일(JSON)을 읽어 반환합니다.
 */
export async function GET(request: Request) {
    const { searchParams } = new URL(request.url);
    const type = searchParams.get('type') || 'original'; // original, aggressive, conviction
    
    const GITHUB_BASE = 'https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data';
    const stateFile = `sim_${type}_state.json`;
    const url = `${GITHUB_BASE}/${stateFile}`;

    try {
        const res = await fetch(url, { cache: 'no-store' });
        if (!res.ok) throw new Error(`Fetch failed: ${res.statusText}`);
        
        const rawData = await res.text();
        return NextResponse.json({
            success: true,
            type: type,
            state: JSON.parse(rawData)
        });
    } catch (error: any) {
        console.error(`[API] Failed to fetch simulator state (${type}) from GitHub:`, error.message);
        
        // 파일이 없을 경우 기본 초기값 반환 (V8.6.2 규격 300만 원)
        return NextResponse.json({
            success: false,
            message: "State file not found, returning default",
            state: {
                cash: SIM_INITIAL_CASH,
                portfolio: {},
                history: [],
                initial_cash: SIM_INITIAL_CASH
            }
        });
    }
}
