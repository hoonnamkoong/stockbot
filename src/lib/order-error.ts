/**
 * 주문 실패를 **두 갈래로 가른다**: 증권사가 거절한 것과 시스템이 고장난 것.
 *
 * ## 왜 필요한가 (2026-09-10 감사)
 *
 * `/api/trade/order`의 catch가 **모든 예외**를 `{success:false, rejected:true}` +
 * status 200으로 돌려줬다. 주석엔 "대시보드에서 에러를 보여주려고"라고 적혀 있었다.
 * 그런데 파이썬 호출부(`place_order_via_vercel`)는 `rejected`를 보면 경고만 찍고
 * 넘어간다 — 그게 "시장이 거부했다"는 뜻이니까.
 *
 * 결과: **KIS 네트워크 실패·토큰 만료·코드 버그가 전부 "시장 사유"로 위장됐다.**
 * 시스템 고장을 시장 판단으로 바꿔 적는 것이고,
 * `no-fabricated-financial-values`가 금지하는 바로 그 모양이다.
 *
 * ## 판정 방향은 fail-closed다
 *
 * **명시적으로 표시된 것만 거부로 본다.** 모르는 예외는 시스템 고장이다.
 * 반대로 하면(모르는 것을 거부로) 새 실패 유형이 생길 때마다 조용히 삼켜진다 —
 * 지금 고치는 사고가 정확히 그 형태였다.
 */

/** 증권사(또는 가상 원장)가 실제로 거절했다. 시스템은 정상 동작했다. */
export function brokerRejection(message: string): Error {
    const e = new Error(message);
    (e as any).brokerRejected = true;
    return e;
}

/**
 * 응답 형태를 정한다.
 * - 거부 → 200 + `rejected:true` (호출부가 경고만 찍고 다음 종목으로 넘어간다)
 * - 고장 → 502 + `rejected:false` (호출부가 예외를 올린다)
 *
 * 502를 고른 이유: 이 라우트가 실패하는 경우는 거의 전부 상류(KIS·GitHub) 실패다.
 * 상태 코드가 무엇이든 파이썬은 `!= 200`이면 raise하고, 두 화면은 이미
 * `error.response?.data?.error`를 읽으므로 메시지는 그대로 보인다.
 */
export function classifyOrderFailure(error: any): { rejected: boolean; status: number } {
    return (error as any)?.brokerRejected === true
        ? { rejected: true, status: 200 }
        : { rejected: false, status: 502 };
}
