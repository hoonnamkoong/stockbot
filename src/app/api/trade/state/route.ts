import { NextResponse } from 'next/server';
import { SIM_INITIAL_CASH } from '@/lib/sim-registry.generated';
import { validateSimStateType } from '@/lib/url-param-validation';

/**
 * [V8.9.9] 시뮬레이터 상태 동기화 API (Remote DB Version)
 * GitHub Raw 디렉토리의 시뮬레이터 상태 파일(JSON)을 읽어 반환합니다.
 */
export async function GET(request: Request) {
    const { searchParams } = new URL(request.url);
    const type = searchParams.get('type');

    // 예전엔 없으면 'original'(은퇴한 구 심 이름, aggressive/conviction과 함께 폐기)로
    // 폴백했다. 그 이름은 등록부(SIM_REGISTRY)에 없어 지금 폴백을 태우면 그대로
    // 400이 난다 — 그렇다고 현재 심 중 하나를 임의로 골라 대신 반환하면, 호출부가
    // type을 빠뜨렸을 때 엉뚱한 심의 상태를 "정상 응답"으로 받게 된다(등록부에
    // 실제 기본 심 개념이 없다). type은 필수로 만들고 이유를 명시한다.
    if (!type) {
        return NextResponse.json(
            { success: false, error: 'type 파라미터가 필요합니다 (예: psych, sim4_bull, libero)' },
            { status: 400 },
        );
    }

    // type을 검증 없이 raw.githubusercontent URL에 보간하면 경로 이탈이 된다.
    // 등록부(SIM_REGISTRY/ANALYZERS)에 있는 값만 통과시킨다.
    const validated = validateSimStateType(type);
    if (!validated.ok) {
        return NextResponse.json({ success: false, error: validated.error }, { status: 400 });
    }

    const GITHUB_BASE = 'https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data';
    const stateFile = `sim_${validated.value}_state.json`;
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
