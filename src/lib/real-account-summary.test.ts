import { test } from 'node:test';
import assert from 'node:assert';
import {
  buildPriceMap, summarizeAccount, summarizeProgram, summarizeTurn,
} from './real-account-summary.ts';

// 실제 돈이다. 못 구한 값은 0이 아니라 null로 올라와야 한다.

// ── 계좌 전체 ───────────────────────────────────────────────────────

test('보유 종목의 평가금액·평가손익·수익률을 만든다', () => {
  const s = summarizeAccount({
    deposit: 500_000,
    holdings: [
      { code: 'A', qty: 10, price: 11_000, pl_amount: 10_000 },
      { code: 'B', qty: 5, price: 2_000, pl_amount: -1_000 },
    ],
  });
  assert.equal(s.deposit, 500_000);
  assert.equal(s.totalEval, 120_000);
  assert.equal(s.totalPL, 9_000);
  // 원가 = 120,000 - 9,000 = 111,000
  assert.equal(s.roiPct!.toFixed(2), '8.11');
});

test('0주 종목은 표에서 뺀다 — 매도 체결 직후 잔고에 잠깐 남는다', () => {
  const s = summarizeAccount({ holdings: [{ code: 'A', qty: 0, price: 1000 }, { code: 'B', quantity: 0, price: 1000 }] });
  assert.deepEqual(s.holdings, []);
  assert.equal(s.totalEval, 0);
});

test('보유가 없으면 수익률 0% — 포지션이 없으니 수익도 없다', () => {
  assert.equal(summarizeAccount({ holdings: [] }).roiPct, 0);
  assert.equal(summarizeAccount(null).roiPct, 0);
});

test('보유는 있는데 원가가 0이면 측정 불가다 — Infinity%를 그리지 않는다', () => {
  // 평가금액 == 평가손익 이면 원가가 0이다. 예전에는 그대로 나눠 Infinity가 나왔다.
  const s = summarizeAccount({ holdings: [{ code: 'A', qty: 1, price: 1000, pl_amount: 1000 }] });
  assert.equal(s.roiPct, null);
});

// ── 시세 맵 ─────────────────────────────────────────────────────────

test('잔고에서 종목코드→현재가를 뽑는다', () => {
  assert.deepEqual(buildPriceMap([{ code: 'A', price: '1500' }, { code: 'B', price: 2000 }]), { A: 1500, B: 2000 });
});

test('code 없는 행과 빈 잔고를 견딘다', () => {
  assert.deepEqual(buildPriceMap([{ price: 100 }, null]), {});
  assert.deepEqual(buildPriceMap(null), {});
});

// ── 프로그램 매매 ───────────────────────────────────────────────────

const POS = { A: { name: 'A', quantity: 10, avg_price: 1_000 } };

test('미실현은 자체 원장 평단 기준이다 — 브로커 계좌 전체와 섞지 않는다', () => {
  const p = summarizeProgram({ positions: POS, prices: { A: 1_200 }, realizedPnl: 5_000, budget: 1_000_000 });
  assert.equal(p.unrealizedPnl, 2_000);
  assert.equal(p.totalPnl, 7_000);
  assert.equal(p.holdingsValue, 12_000);
  assert.equal(p.ratePct!.toFixed(2), '0.70');
});

test('시세를 못 붙인 종목은 기여분 0이다 — 0원으로 평가하면 원금 전액 손실로 보인다', () => {
  // 예전 버그: 미실현은 ??를 써서 price 0이 통과해 (0-1000)*10 = -10,000이 됐고,
  // 보유 총액은 ||를 써서 평단으로 떨어졌다. 같은 결측에 두 계산이 다르게 반응했다.
  for (const prices of [{ A: 0 }, {}, { A: -1 }]) {
    const p = summarizeProgram({ positions: POS, prices, realizedPnl: 0, budget: 1_000_000 });
    assert.equal(p.unrealizedPnl, 0, JSON.stringify(prices));
    assert.equal(p.holdingsValue, 10_000, JSON.stringify(prices));
  }
});

test('예산이 없으면 수익률은 측정 불가다 — 0%로 그리면 손익 0과 구분이 사라진다', () => {
  const p = summarizeProgram({ positions: POS, prices: { A: 1_200 }, realizedPnl: 0, budget: 0 });
  assert.equal(p.ratePct, null);
  assert.equal(p.totalPnl, 2_000, '수익률은 못 만들어도 손익 금액은 값이 있다');
});

test('예산·포지션·실현손익 중 하나라도 있으면 프로그램 지표를 띄운다', () => {
  const none = summarizeProgram({ positions: {}, prices: {}, realizedPnl: 0, budget: 0 });
  assert.equal(none.hasData, false);
  assert.equal(summarizeProgram({ positions: POS, prices: {}, realizedPnl: 0, budget: 0 }).hasData, true);
  assert.equal(summarizeProgram({ positions: {}, prices: {}, realizedPnl: -1, budget: 0 }).hasData, true);
  assert.equal(summarizeProgram({ positions: {}, prices: {}, realizedPnl: 0, budget: 1 }).hasData, true);
});

// ── 턴 ─────────────────────────────────────────────────────────────

const TURN = { id: 't1', capital: 1_000_000, basis: { A: 1_000 }, by_tag: { sim_psych: 3_000 }, active_tag: 'sim_psych' };

test('ON이면 원장 턴으로 실시간 계산한다', () => {
  const t = summarizeTurn({ turn: TURN, lastTurn: null, positions: POS, prices: { A: 1_100 }, programEnabled: true });
  assert.equal(t.isLive, true);
  assert.equal(t.measurable, true);
  // 확정 3,000 + 미실현 (1,100-1,000)*10 = 1,000
  assert.equal(t.pnl, 4_000);
  assert.equal(t.ratePct!.toFixed(2), '0.40');
  assert.deepEqual(t.tagRows, [['sim_psych', 4_000]]);
});

test('OFF면 동결된 직전 턴을 쓴다', () => {
  const last = { id: 't0', ended_at: '', sim: null, capital: 500_000, pnl: -5_000, by_tag: { sim_bull: -5_000 } };
  const t = summarizeTurn({ turn: null, lastTurn: last, positions: POS, prices: { A: 9_999 }, programEnabled: false });
  assert.equal(t.isLive, false);
  assert.equal(t.pnl, -5_000, '보유 시세가 아무리 변해도 동결된 값이다');
  assert.equal(t.measurable, true);
});

test('직전 턴의 pnl이 null이면 측정 불가다 — 진짜 0원 턴과 구분한다', () => {
  const last = { id: 't0', ended_at: '', sim: null, capital: 500_000, pnl: null, by_tag: {} };
  const t = summarizeTurn({ turn: null, lastTurn: last, positions: {}, prices: {}, programEnabled: false });
  assert.equal(t.has, true);
  assert.equal(t.measurable, false);
});

test('원금이 0이면 측정 불가다', () => {
  const last = { id: 't0', ended_at: '', sim: null, capital: 0, pnl: 0, by_tag: {} };
  assert.equal(summarizeTurn({ turn: null, lastTurn: last, positions: {}, prices: {}, programEnabled: false }).measurable, false);
});

test('턴이 아예 없으면 has가 false다 — "껐다 켜면 시작"', () => {
  const t = summarizeTurn({ turn: null, lastTurn: null, positions: {}, prices: {}, programEnabled: true });
  assert.equal(t.has, false);
});

test('파이썬이 아직 안 돈 턴은 전략별 귀속이 미확정이다', () => {
  const fresh = { ...TURN, by_tag: {}, active_tag: null };
  const t = summarizeTurn({ turn: fresh, lastTurn: null, positions: {}, prices: {}, programEnabled: true });
  assert.equal(t.pendingFirstRun, true);
});

test('ON이어도 턴이 없으면 실시간이 아니다 — 동결값으로 떨어진다', () => {
  const last = { id: 't0', ended_at: '', sim: null, capital: 100, pnl: 7, by_tag: {} };
  const t = summarizeTurn({ turn: null, lastTurn: last, positions: {}, prices: {}, programEnabled: true });
  assert.equal(t.isLive, false);
  assert.equal(t.pnl, 7);
});

test('손익 0인 태그는 목록에서 빼고 큰 순서로 세운다', () => {
  const turn = { ...TURN, basis: {}, by_tag: { a: 100, b: 0, c: -50, d: 900 }, active_tag: 'a' };
  const t = summarizeTurn({ turn, lastTurn: null, positions: {}, prices: {}, programEnabled: true });
  assert.deepEqual(t.tagRows, [['d', 900], ['a', 100], ['c', -50]]);
});
