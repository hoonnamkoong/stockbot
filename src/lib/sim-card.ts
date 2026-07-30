/**
 * 심 카드가 state JSON을 화면 숫자로 바꾸는 규칙.
 *
 * TradeClient.tsx의 renderSimulationTripod 안에 인라인돼 있던 계산이다.
 * 순수 함수라 node 테스트가 그대로 읽는다.
 *
 * 여기 있는 것은 **표시 계산일 뿐 성과 산정이 아니다.** 심의 수익률 정본은
 * 파이썬이 state에 써둔 값이고, 이 파일은 그것을 다시 계산하지 않는다.
 */

/** 심 전체가 300만으로 출발한다는 동일조건. 파이썬 쪽 상수와 짝이다. */
export const SIM_INITIAL_CASH = 3_000_000;

export type SimHolding = {
  code: string; name: string; qty: number;
  avg_price: number; current_price: number; pl_rate: number;
};

/**
 * state의 portfolio(딕셔너리)를 표 한 줄들로 편다.
 *
 * 현재가는 `stats.current_prices`에 따로 있다 — 없으면 평단을 쓴다(등락 0%).
 * 지어낸 시세가 아니라 "아직 시세를 못 붙였다"는 뜻이고, 0원으로 그리면
 * 평가금액이 통째로 0이 되어 훨씬 큰 거짓이 된다.
 */
export function deriveSimHoldings(
  portfolio: Record<string, any> | null | undefined,
  currentPrices: Record<string, number> | null | undefined,
): SimHolding[] {
  if (!portfolio) return [];
  return Object.keys(portfolio).map((code) => {
    const p = portfolio[code];
    const avg = p.avg_price || p.price || 0;
    const cur = currentPrices?.[code] ?? avg;
    return {
      code,
      name: p.name,
      qty: p.quantity,
      avg_price: avg,
      current_price: cur,
      pl_rate: avg > 0 ? ((cur - avg) / avg) * 100 : 0,
    };
  });
}

/**
 * 누적 수익 = NAV − 초기자본. 수수료는 이미 현금에서 차감돼 있다.
 *
 * `total_asset`이 없으면 `cash`로 떨어진다 — 보유가 없는 심은 그게 곧 NAV다.
 */
export function computeNetPL(stats: { total_asset?: number; cash?: number } | null | undefined): number {
  return Math.round((stats?.total_asset || stats?.cash || 0) - SIM_INITIAL_CASH);
}

/** 금일(KST) 거래 종목수. 매수·매도를 합쳐 종목 중복을 제거한다. */
export function countTodayTickers(
  history: { type?: string; time?: string; symbol?: string }[],
  simType: string,
  todayKST: string,
): number {
  const today = history.filter((h) => h.type === simType && h.time?.startsWith(todayKST));
  return new Set(today.map((h) => h.symbol)).size;
}

/** KST 달력 날짜(`YYYY-MM-DD`). 서버 시간대가 무엇이든 장 기준일을 준다. */
export function todayKST(now: Date = new Date()): string {
  return now.toLocaleDateString('en-CA', { timeZone: 'Asia/Seoul' });
}
