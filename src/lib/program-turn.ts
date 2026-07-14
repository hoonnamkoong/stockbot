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
        const b = Number(basis[code] ?? px);
        const tag = pos.tag || turn.active_tag || 'unknown';
        byTag[tag] = (byTag[tag] || 0) + (px - b) * pos.quantity;
    }

    const pnl = Object.values(byTag).reduce((s, v) => s + v, 0);
    return { pnl, byTag };
}
