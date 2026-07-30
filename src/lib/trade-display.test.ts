import { test } from 'node:test';
import assert from 'node:assert';
import { derivePosition, pnlColor, roiCells, signed, splitTimestamp } from './trade-display.ts';

// 실거래 화면의 숫자다. 화면 테스트는 없지만 숫자가 어떻게 나오는지는 여기서 지킨다.

test('잔고 API 필드(qty/avg_price)로 한 줄을 만든다', () => {
  const p = derivePosition({ qty: 10, avg_price: 1000, current_price: 1100, pl_rate: 10, pl_amount: 1000 });
  assert.deepEqual(p, { qty: 10, avgPrice: 1000, currentPrice: 1100, amount: 10_000, plAmount: 1000, plRate: 10 });
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
