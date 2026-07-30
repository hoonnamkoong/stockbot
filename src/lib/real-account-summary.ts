/**
 * 실전 계좌 화면의 요약 숫자 — 계좌 전체 / 프로그램 매매 / 턴.
 *
 * TradeClient.tsx의 renderRealPortfolioSection 머리에 47줄로 인라인돼 있던 계산이다.
 * **여기 있는 값은 전부 실제 돈이다.** 그래서 화면 테스트가 없는 UI에서도 숫자만은
 * node 테스트가 지킨다 — [[no-fabricated-financial-values]].
 *
 * 규칙: 못 구한 값은 `null`로 올린다. 호출부가 '측정 불가'로 그리게 하기 위한 것이고,
 * 0을 올리면 '손익 0원'과 구분이 사라진다.
 */

// `.ts` 확장자를 붙여야 node --test가 읽는다(sim-reset-targets.ts와 같은 이유).
import { computeTurnPnl, type LastTurnResult, type ProgramPosition, type ProgramTurn } from './program-turn.ts';

/** 종목코드 → 현재가. 잔고 응답에서 뽑는다(프로그램 원장에는 시세가 없다). */
export function buildPriceMap(holdings: any[] | null | undefined): Record<string, number> {
    const map: Record<string, number> = {};
    for (const h of holdings || []) if (h?.code) map[h.code] = Number(h.price) || 0;
    return map;
}

/**
 * 계좌 전체 요약.
 *
 * 0주 종목은 표에서 뺀다 — 매도가 체결되면 잔고 응답에 0주로 잠깐 남는다.
 * `roiPct`는 원가(평가금액 − 평가손익) 기준이고, 계산이 성립하지 않으면 `null`이다.
 */
export function summarizeAccount(balance: { deposit?: number; holdings?: any[] } | null | undefined): {
    deposit: number; holdings: any[]; totalEval: number; totalPL: number; roiPct: number | null;
} {
    const holdings = (balance?.holdings || []).filter((h: any) => Number(h.qty || h.quantity || 0) > 0);
    const totalEval = holdings.reduce((sum: number, h: any) => sum + ((h.price || 0) * (h.qty || 0)), 0);
    const totalPL = holdings.reduce((sum: number, h: any) => sum + (h.pl_amount || 0), 0);

    // 보유가 없으면 수익률이 0%다(포지션이 없으니 수익도 없다 — 이건 지어낸 값이 아니다).
    // 반대로 보유는 있는데 원가가 0이면 나눗셈이 성립하지 않는다 → 측정 불가.
    let roiPct: number | null = 0;
    if (totalEval > 0) {
        const costBasis = totalEval - totalPL;
        roiPct = costBasis > 0 ? (totalPL / costBasis) * 100 : null;
    }
    return { deposit: Number(balance?.deposit ?? 0) || 0, holdings, totalEval, totalPL, roiPct };
}

/**
 * 프로그램 매매 누적 요약.
 *
 * 미실현은 **자체 원장의 avg_price**를 기준가로 쓴다 — 브로커 계좌 전체 손익과
 * 섞이면 프로그램의 성과가 아니게 된다. 시세를 못 붙인 종목은 기여분 0이다
 * (기준가를 현재가로 쓰는 것과 같다 — 없는 시세를 지어내지 않는다).
 */
export function summarizeProgram(args: {
    positions: Record<string, ProgramPosition>;
    prices: Record<string, number>;
    realizedPnl: number;
    budget: number;
}): { unrealizedPnl: number; totalPnl: number; ratePct: number | null; holdingsValue: number; hasData: boolean } {
    const entries = Object.entries(args.positions || {});
    const unrealizedPnl = entries.reduce((sum, [code, pos]) => {
        const px = args.prices[code];
        const currentPrice = px != null && px > 0 ? px : pos.avg_price;
        return sum + (currentPrice - pos.avg_price) * pos.quantity;
    }, 0);
    const holdingsValue = entries.reduce((sum, [code, pos]) => {
        const px = args.prices[code];
        return sum + ((px != null && px > 0 ? px : pos.avg_price) * pos.quantity);
    }, 0);

    const totalPnl = args.realizedPnl + unrealizedPnl;
    return {
        unrealizedPnl,
        totalPnl,
        // 예산(분모)이 없으면 수익률을 만들 수 없다.
        ratePct: args.budget > 0 ? (totalPnl / args.budget) * 100 : null,
        holdingsValue,
        hasData: args.budget > 0 || entries.length > 0 || args.realizedPnl !== 0,
    };
}

export type TurnSummary = {
    /** 표시할 턴이 아예 없다 — "껐다 켜면 시작". */
    has: boolean;
    /** ON이라 원장 turn으로 실시간 계산 중(항상 측정 가능). false면 동결된 직전 턴. */
    isLive: boolean;
    capital: number;
    /** 원금이 없거나 직전 턴이 조회 실패로 동결됐다 → 0%가 아니라 측정 불가. */
    measurable: boolean;
    /** 파이썬이 이 턴을 아직 한 번도 안 돌았다 — 전략별 귀속이 미확정. */
    pendingFirstRun: boolean;
    pnl: number;
    ratePct: number;
    byTag: Record<string, number>;
    /** 손익 0인 태그는 빼고 큰 순서. 합계가 턴 수익률이다. */
    tagRows: [string, number][];
};

/**
 * 턴 요약. ON이면 원장 turn으로 실시간, OFF면 config에 동결된 직전 턴이다.
 *
 * 직전 턴의 `pnl === null`은 OFF 시점 조회 실패다 — 진짜 0원 턴과 반드시 구분한다.
 */
export function summarizeTurn(args: {
    turn: ProgramTurn | null;
    lastTurn: LastTurnResult | null;
    positions: Record<string, ProgramPosition>;
    prices: Record<string, number>;
    programEnabled: boolean;
}): TurnSummary {
    const live = args.turn ? computeTurnPnl(args.turn, args.positions, args.prices) : null;
    const isLive = args.programEnabled && !!args.turn;
    const capital = args.turn?.capital ?? args.lastTurn?.capital ?? 0;
    const pnl = live ? live.pnl : (args.lastTurn?.pnl ?? 0);
    const byTag = live ? live.byTag : (args.lastTurn?.by_tag ?? {});

    return {
        has: !!args.turn || !!args.lastTurn,
        isLive,
        capital,
        measurable: (isLive || args.lastTurn?.pnl != null) && capital > 0,
        pendingFirstRun: isLive && args.turn?.active_tag == null,
        pnl,
        ratePct: capital > 0 ? (pnl / capital) * 100 : 0,
        byTag,
        tagRows: Object.entries(byTag).filter(([, v]) => v !== 0).sort((a, b) => b[1] - a[1]),
    };
}
