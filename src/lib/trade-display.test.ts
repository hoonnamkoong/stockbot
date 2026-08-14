import { test } from 'node:test';
import assert from 'node:assert';
import { derivePosition, pnlColor, roiCells, signed, splitTimestamp } from './trade-display.ts';

// 실거래 화면의 숫자다. 화면 테스트는 없지만 숫자가 어떻게 나오는지는 여기서 지킨다.

test('잔고 API 필드(qty/avg_price)로 한 줄을 만든다', () => {
  const p = derivePosition({ qty: 10, avg_price: 1000, current_price: 1100, pl_rate: 10, pl_amount: 1000 });
  assert.deepEqual(p, { qty: 10, avgPrice: 1000, currentPrice: 1100, amount: 10_000, evalAmount: 11_000, plAmount: 1000, plRate: 10, priceKnown: true });
});

test('현재금액은 현재가 기준이다 — 체결금액과의 차이가 곧 평가손익이다', () => {
  const p = derivePosition({ qty: 6, avg_price: 45_050, current_price: 45_350 });
  assert.equal(p.amount, 270_300);        // 투입 원금
  assert.equal(p.evalAmount, 272_100);    // 지금 팔면 받는 값(수수료·세금 전)
  assert.equal(p.evalAmount - p.amount, p.plAmount);
});

test('시세를 모르면 현재금액도 모른다 — 체결금액으로 메우지 않는다', () => {
  // 평단으로 폴백하면 '안 움직였다'는 거짓이 되고, 손익 0원과 구분이 사라진다.
  const p = derivePosition({ qty: 10, avg_price: 1000, current_price: 0 });
  assert.equal(p.priceKnown, false);
  assert.equal(p.evalAmount, null);
});

test('심 상태 필드(quantity/price)도 같은 줄이 된다', () => {
  // 두 소스가 필드명이 달라서, 한쪽만 보면 다른 쪽 표가 통째로 0이 된다.
  const p = derivePosition({ quantity: 5, price: 2000 });
  assert.equal(p.qty, 5);
  assert.equal(p.avgPrice, 2000);
  assert.equal(p.currentPrice, 2000);
});

test('체결금액은 평단 기준이다 — 현재가로 곱하면 평가금액이 되어 다른 뜻이 된다', () => {
  const p = derivePosition({ qty: 10, avg_price: 1000, current_price: 5000 });
  assert.equal(p.amount, 10_000);
});

test('손익이 안 오면 (현재가-평단)×수량으로 만든다', () => {
  assert.equal(derivePosition({ qty: 10, avg_price: 1000, current_price: 900 }).plAmount, -1000);
});

test('서버가 준 손익이 있으면 그것을 쓴다 — 0원도 값이다', () => {
  const p = derivePosition({ qty: 10, avg_price: 1000, current_price: 9999, pl_amount: 0 });
  assert.equal(p.plAmount, 0, '?? 대신 ||를 쓰면 0이 사라져 엉뚱한 숫자로 대체된다');
});

test('심이 평단으로 때운 행은 시세 미확인이다 — 등락률을 그리면 안 된다', () => {
  const p = derivePosition({ qty: 1, avg_price: 5000, current_price: 5000, price_known: false });
  assert.equal(p.priceKnown, false);
});

test('현재가가 0이면 시세 미확인이다', () => {
  assert.equal(derivePosition({ qty: 1, avg_price: 5000, current_price: 0 }).priceKnown, false);
});

test('실거래 잔고 행은 플래그가 없어도 시세가 있으면 확인된 것이다', () => {
  assert.equal(derivePosition({ qty: 10, avg_price: 1000, current_price: 1100 }).priceKnown, true);
});

test('색은 이익 빨강·손실 파랑, 0은 이익 쪽', () => {
  assert.equal(pnlColor(1), 'red');
  assert.equal(pnlColor(0), 'red');
  assert.equal(pnlColor(-1), 'blue');
});

test('부호는 양수에만 붙고 천단위가 들어간다', () => {
  assert.equal(signed(1234567), '+1,234,567');
  assert.equal(signed(-1234567), '-1,234,567');
  assert.equal(signed(0), '+0');
});

// ── 실거래 ROI 두 칸 ────────────────────────────────────────────────

test('ROI가 있으면 % 와 금액을 그린다', () => {
  const { pct, amount } = roiCells({ action: 'SELL', roi: '+3.5', roiAmount: 35_000 });
  assert.deepEqual(pct, { kind: 'value', text: '+3.5%', color: 'red' });
  assert.deepEqual(amount, { kind: 'value', text: '+35,000원', color: 'red' });
});

test('손실은 파랑', () => {
  const { pct, amount } = roiCells({ action: 'SELL', roi: '-2.0', roiAmount: -20_000 });
  assert.equal((pct as any).color, 'blue');
  assert.equal((amount as any).color, 'blue');
});

test('매도인데 값이 없으면 0%가 아니라 측정 불가다', () => {
  for (const h of [
    { action: 'SELL' },
    { action: 'SELL', roi: null },
    { action: 'SELL', roi: '-' },
  ]) {
    const { pct, amount } = roiCells(h as any);
    assert.equal(pct.kind, 'unmeasurable', JSON.stringify(h));
    assert.equal(amount.kind, 'unmeasurable');
  }
});

test('매수 행은 측정 불가가 아니라 빈 칸이다 — 살 때는 실현손익이 없는 게 정상이다', () => {
  const { pct, amount } = roiCells({ action: 'BUY' });
  assert.equal(pct.kind, 'none');
  assert.equal(amount.kind, 'none');
});

test('%는 왔는데 금액이 없으면 금액만 측정 불가다', () => {
  const { pct, amount } = roiCells({ action: 'SELL', roi: '+1.0' });
  assert.equal(pct.kind, 'value');
  assert.equal(amount.kind, 'unmeasurable');
});

test('ROI를 아예 기록하지 않는 파일은 측정 불가가 아니라 빈 칸이다', () => {
  // 심 CSV의 구 포맷. 실패한 게 아니라 그 열이 생기기 전 기록이다.
  const { pct, amount } = roiCells({ action: 'SELL', roi: null, roiTracked: false });
  assert.equal(pct.kind, 'none');
  assert.equal(amount.kind, 'none');
});

test('기록하는 파일인데 매도에 값이 없으면 여전히 측정 불가다', () => {
  const { pct } = roiCells({ action: 'SELL', roi: null, roiTracked: true });
  assert.equal(pct.kind, 'unmeasurable');
});

test('실현손익 0원은 값이다 — 측정 불가로 뭉개지 않는다', () => {
  const { amount } = roiCells({ action: 'SELL', roi: '0.0', roiAmount: 0 });
  assert.deepEqual(amount, { kind: 'value', text: '+0원', color: 'gray' });
});

// ── 기록 시각 ───────────────────────────────────────────────────────

test('시각은 MM-DD 와 HH:mm:ss 두 줄로 쪼갠다', () => {
  assert.deepEqual(splitTimestamp('2026-07-30 14:05:06'), { date: '07-30', clock: '14:05:06' });
});

test('시각이 없거나 형태가 다르면 표가 죽지 않는다', () => {
  // 예전에는 h.time.split(...)을 바로 불러, 값 하나가 비면 기록 표 전체가 렌더 에러였다.
  for (const bad of [undefined, null, '', '2026-07-30', 123]) {
    assert.deepEqual(splitTimestamp(bad), { date: '-', clock: '' }, String(bad));
  }
});
