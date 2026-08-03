/**
 * 프로그램 매매 턴 손익 표시 계산 (route의 OFF 동결 + 프론트 실시간 표시 공용).
 *
 * 기록은 파이썬(program_turn.py)이 원장에 한다. 여기서는 확정분(by_tag)에
 * 현재 보유분의 미실현(현재가 − 기준가)을 얹어 '지금 시점의 턴 손익'을 만든다.
 */

export type ProgramTurn = {
    id: string;
    capital: number;
    basis: Record<string, number>;
    by_tag: Record<string, number>;
    active_tag: string | null;
};

export type ProgramPosition = { name: string; quantity: number; avg_price: number; tag?: string };

export type TurnResult = { pnl: number; byTag: Record<string, number> };

/**
 * OFF 시점에 config에 동결되는 직전 턴 결과(표시 전용).
 * pnl === null 이면 '측정 불가'(계산에 필요한 조회가 실패/지연) — 진짜 0원 턴과 반드시 구분해 그린다.
 * degraded가 있으면 by_tag는 비어 있다(부분 합계가 전체인 것처럼 보이지 않게).
 */
/**
 * 실계좌에서 사라져 손익을 계상하지 못한 청산분.
 *
 * 프로그램이 낸 매도만 realized_pnl에 누적되므로, 수동 청산은 원장에서 포지션만
 * 빠지고 손익은 어디에도 남지 않는다. 체결가를 우리가 모르기 때문에 pnl 필드가
 * 없다 — 매입원가(cost_basis)만 적고 '미정산'으로 둔다. 값을 지어내는 대신
 * 누락 사실을 드러내기 위한 타입이다.
 */
export type UnreconciledExit = {
    date: string;
    code: string;
    name: string;
    quantity: number;
    avg_price: number;
    cost_basis: number;
};

export type LastTurnResult = {
    id: string;
    ended_at: string;
    sim: string | null;
    capital: number;
    pnl: number | null;
    by_tag: Record<string, number>;
    degraded?: 'ledger_unavailable' | 'prices_unavailable' | 'timeout';
};

/**
 * 턴 손익 = 확정분(by_tag) + 보유분 미실현(각 종목의 tag에 귀속).
 * 시세를 못 구한 종목은 기여분 0으로 처리한다(기존 프로그램 평가손익 계산과 동일한 폴백).
 */
export function computeTurnPnl(
    turn: ProgramTurn | null | undefined,
    positions: Record<string, ProgramPosition>,
    prices: Record<string, number>,
): TurnResult {
    if (!turn || !turn.id) return { pnl: 0, byTag: {} };

    const byTag: Record<string, number> = { ...(turn.by_tag || {}) };
    const basis = turn.basis || {};

    for (const [code, pos] of Object.entries(positions || {})) {
        const px = Number(prices[code]) || 0;
        if (px <= 0) continue;
        // ||(falsy 폴백): 파이썬 new_turn()의 `or` 체인과 동일. basis에 0이 들어오면
        // ??는 0을 통과시켜 (px-0)*qty = 시가총액 전체가 턴 수익으로 계상된다.
        const b = Number(basis[code] || px);
        const tag = pos.tag || turn.active_tag || 'unknown';
        byTag[tag] = (byTag[tag] || 0) + (px - b) * pos.quantity;
    }

    const pnl = Object.values(byTag).reduce((s, v) => s + v, 0);
    return { pnl, byTag };
}
