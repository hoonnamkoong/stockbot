/**
 * 실거래·시뮬 표가 숫자를 화면 값으로 바꾸는 규칙.
 *
 * TradeClient.tsx(1,040줄) 안의 표 렌더 함수에 흩어져 있던 계산이다. 여기 있는 것은
 * 전부 순수 함수라 node 테스트가 그대로 읽는다 — 화면 테스트가 없는 실거래 UI에서
 * **적어도 숫자가 어떻게 나오는지는** 테스트가 지킨다.
 *
 * 원칙: 모르는 값을 0이나 0%로 그리지 않는다. 실현손익을 확보 못 한 매도는
 * '측정 불가'다 — [[no-fabricated-financial-values]].
 */

/** 보유 종목 한 줄의 표시값. 잔고 API와 심 상태가 필드명이 달라 양쪽을 받아준다. */
export function derivePosition(h: any): {
  qty: number; avgPrice: number; currentPrice: number; amount: number;
  plRate: number; plAmount: number;
} {
  const qty = h.qty || h.quantity || 0;
  const avgPrice = h.avg_price || h.price || 0;
  const currentPrice = h.current_price || h.price || 0;
  const plRate = h.pl_rate ?? 0;
  // 체결금액은 평단 기준이다(투입 원금). 현재가로 곱하면 평가금액이 되어 다른 뜻이 된다.
  const amount = qty * avgPrice;
  const plAmount = h.pl_amount ?? Math.round((currentPrice - avgPrice) * qty);
  return { qty, avgPrice, currentPrice, amount, plAmount, plRate };
}

/** 국내 관례: 이익은 빨강, 손실은 파랑. */
export function pnlColor(v: number): 'red' | 'blue' {
  return v >= 0 ? 'red' : 'blue';
}

export function signed(v: number): string {
  return (v >= 0 ? '+' : '') + Math.round(v).toLocaleString();
}

export type RoiCell = { kind: 'value'; text: string; color: 'red' | 'blue' | 'gray' }
                    | { kind: 'unmeasurable' }
                    | { kind: 'none' };

/**
 * 실거래 기록의 ROI 두 칸(%, 금액).
 *
 * 값이 없을 때 매도는 '측정 불가', 매수는 '-'다. 매도에 값이 없다는 것은 원가를
 * 확보하지 못했다는 뜻이지 손익이 0이라는 뜻이 아니다(kis-api.matchRealizedRoi).
 */
export function roiCells(h: { action?: string; roi?: string | null; roiAmount?: number | null }): {
  pct: RoiCell; amount: RoiCell;
} {
  const isSell = h.action === 'SELL';
  const missing: RoiCell = isSell ? { kind: 'unmeasurable' } : { kind: 'none' };
  const hasRoi = h.roi !== undefined && h.roi !== null && h.roi !== '-';
  if (!hasRoi) return { pct: missing, amount: missing };

  const roi = h.roi as string;
  const pctColor = roi.startsWith('+') ? 'red' : roi.startsWith('-') ? 'blue' : 'gray';
  const amount: RoiCell = h.roiAmount === undefined || h.roiAmount === null
    ? missing
    : {
        kind: 'value',
        text: `${signed(h.roiAmount)}원`,
        color: h.roiAmount > 0 ? 'red' : h.roiAmount < 0 ? 'blue' : 'gray',
      };
  return { pct: { kind: 'value', text: `${roi}%`, color: pctColor }, amount };
}

/** 기록 시각을 두 줄로 쪼갠다 — 위는 `MM-DD`, 아래는 `HH:mm:ss`. */
export function splitTimestamp(time: unknown): { date: string; clock: string } {
  if (typeof time !== 'string' || !time.includes(' ')) return { date: '-', clock: '' };
  const [d, t] = time.split(' ');
  return { date: d.slice(5), clock: t };
}
