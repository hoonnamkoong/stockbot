import { test } from 'node:test';
import assert from 'node:assert';
import { summarizeRealizedBuckets, type ProfitEntry } from './kis-api.ts';

/**
 * 화면의 "KIS 실측 실현손익"이 2026-08-14에 '측정 불가'로 떠 있었다.
 *
 * 원인: getRealizedProfitBuckets가 **조회 실패**와 **그 기간에 매도가 없음**을
 * 둘 다 빈 Map으로 돌려줘서, 호출부가 구분할 수 없었다. 그래서 판 게 없는
 * 날에도 '측정 불가'가 떴고, 그러면 진짜 조회 실패를 알아챌 방법이 사라진다.
 *
 * Python 쪽(src/trade/realized_pnl.py)은 같은 구분을 이미 하고 있었다 —
 * TS만 안 되어 있었다.
 */

const entry = (roiAmount: number): ProfitEntry =>
  ({ sellQty: 1, roiPct: '+1.0', roiAmount });

test('조회 실패는 측정 불가다 — 0원으로 위장하지 않는다', () => {
  const out = summarizeRealizedBuckets(false, new Map());
  assert.equal(out.ok, false);
});

test('조회는 됐는데 매도가 없으면 0원이다 — 이게 측정 불가로 표시되던 버그', () => {
  const out = summarizeRealizedBuckets(true, new Map());
  assert.equal(out.ok, true);
  assert.equal(out.total, 0);
});

test('여러 종목·여러 건을 합산한다', () => {
  const buckets = new Map<string, ProfitEntry[]>([
    ['005930_20260814', [entry(1000), entry(-300)]],
    ['000660_20260813', [entry(500)]],
  ]);
  const out = summarizeRealizedBuckets(true, buckets);
  assert.equal(out.ok, true);
  assert.equal(out.total, 1200);
});

test('손실만 있어도 합계가 음수로 나온다 — 부호를 삼키지 않는다', () => {
  const buckets = new Map<string, ProfitEntry[]>([['A_20260814', [entry(-2500)]]]);
  assert.equal(summarizeRealizedBuckets(true, buckets).total, -2500);
});

test('조회 실패면 버킷에 값이 있어도 측정 불가다', () => {
  const buckets = new Map<string, ProfitEntry[]>([['A_20260814', [entry(9999)]]]);
  const out = summarizeRealizedBuckets(false, buckets);
  assert.equal(out.ok, false);
  assert.equal(out.total, 0);
});
