/**
 * 수동 주문 기록 한 줄 조립 — 순수 함수.
 *
 * 떼어낸 이유는 실제 사고다. 라우트가 `price: Number(price) || 0`으로 적었고,
 * **매도는 항상 시장가라**(kis-api.ts의 buildOrderRequest: `side === 'buy' &&
 * ordType === 'limit'`) 주문 시점에 체결가를 모른다. 그래서 수동 매도가 전부
 * `price: 0`으로 박혔다 — 2026-07-08에 발견하고, 2026-11-06에 다섯 건이
 * 똑같이 박혔다. "0원에 팔았다"는 기록은 손익을 계산할 수 없게 만든다.
 *
 * 모르는 값은 null로 적고 `ord_type`으로 **왜 모르는지**까지 남긴다. 0은
 * 숫자라서 뒤에서 그대로 계산에 들어가고, 그러면 조용히 틀린다.
 * 체결가 자체는 KIS에서 받아 메운다(program_trader.settle_unreconciled_exits).
 *
 * 라우트는 node --test에서 import할 수 없어서 여기 두고 테스트한다 —
 * src/lib/program-turn.ts와 같은 이유다.
 */

/**
 * 누가 낸 주문인가. 프로그램은 `Bearer WEBHOOK_SECRET`으로, 사람은 세션+PIN으로
 * 같은 라우트를 지난다 — 라우트는 원래부터 둘을 구분할 수 있었는데 적지 않았다.
 *
 * 2026-11-23에 그 대가를 치렀다. 정산이 "수량이 맞는 매도를 특정하지 못했습니다"로
 * 세 건 막혔는데, 한투 조회에 잡힌 같은 수량 매도 셋 중 둘이 프로그램 매도였다.
 * 기록만 봐서는 구분이 안 돼 사람이 반복 매매한 것으로 오독까지 했다.
 */
export type OrderOrigin = 'program' | 'manual';

export type HistoryEntry = {
    time: string;
    symbol: string;
    action: 'BUY' | 'SELL';
    /** 주문에 실제로 실린 단가. 시장가는 체결가를 모르므로 null(= 측정 불가). */
    price: number | null;
    qty: number;
    /** price가 null인 이유를 기록 자체가 설명하게 한다. */
    ord_type: 'market' | 'limit';
    /** 프로그램이 낸 것인가 사람이 낸 것인가. 정산이 매도일을 특정하는 데 쓴다. */
    origin: OrderOrigin;
    type: 'virtual' | 'real';
    reason: string;
};

/**
 * 주문에 단가가 실렸나. **kis-api.ts의 buildOrderRequest와 같은 규칙이어야 한다**
 * — 다르면 기록과 실제로 보낸 주문이 어긋난다. 그 일치는
 * src/lib/trade-history-entry.test.ts가 두 함수를 같이 불러 못박는다.
 */
export function orderCarriedAPrice(
    side: 'buy' | 'sell',
    ordType: string | undefined,
    price: unknown,
): boolean {
    return side === 'buy' && ordType === 'limit' && Number(price) > 0;
}

export function buildHistoryEntry(args: {
    time: string;
    code: string;
    side: 'buy' | 'sell';
    qty: number;
    price: unknown;
    ordType: string | undefined;
    isVirtual: boolean;
    origin: OrderOrigin;
    reason?: string;
}): HistoryEntry {
    const priced = orderCarriedAPrice(args.side, args.ordType, args.price);
    return {
        time: args.time,
        symbol: args.code,
        action: args.side.toUpperCase() as 'BUY' | 'SELL',
        price: priced ? Number(args.price) : null,
        qty: Number(args.qty),
        ord_type: priced ? 'limit' : 'market',
        origin: args.origin,
        type: args.isVirtual ? 'virtual' : 'real',
        // 사유의 기본값도 출처를 따른다. 'Manual Dashboard Trade'가 프로그램
        // 주문에까지 붙어 있어서 기록을 읽는 사람이 속았다.
        reason: args.reason
            || (args.origin === 'program' ? 'Program Order' : 'Manual Dashboard Trade'),
    };
}
