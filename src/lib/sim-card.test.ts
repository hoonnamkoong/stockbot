import { test } from 'node:test';
import assert from 'node:assert';
import {
  SIM_INITIAL_CASH, computeNetPL, countTodayTickers, deriveSimHoldings, todayKST,
} from './sim-card.ts';

// ── 포트폴리오 펴기 ─────────────────────────────────────────────────

test('portfolio 딕셔너리가 표 줄들이 된다', () => {
  const rows = deriveSimHoldings(
    { '005930': { name: '삼성전자', quantity: 10, avg_price: 70000 } },
    { '005930': 77000 },
  );
  assert.deepEqual(rows, [{
    code: '005930', name: '삼성전자', qty: 10,
    avg_price: 70000, current_price: 77000, pl_rate: 10, price_known: true,
  }]);
});

test('시세를 못 붙였으면 평단을 쓴다 — 0원으로 그리면 평가금액이 통째로 거짓이 된다', () => {
  const [row] = deriveSimHoldings({ A: { name: 'A', quantity: 1, avg_price: 5000 } }, null);
  assert.equal(row.current_price, 5000);
  assert.equal(row.pl_rate, 0);
  assert.equal(row.price_known, false, '평단으로 때운 것을 표시해야 화면이 0%를 안 그린다');
});

test('시세가 0이나 음수로 와도 미확인이다 — 그 값으로 계산하면 전액 손실로 보인다', () => {
  for (const prices of [{ A: 0 }, { A: -1 }, {}]) {
    const [row] = deriveSimHoldings({ A: { name: 'A', quantity: 1, avg_price: 5000 } }, prices);
    assert.equal(row.price_known, false, JSON.stringify(prices));
    assert.equal(row.current_price, 5000);
  }
});

test('실제 시세가 있으면 price_known이 참이다', () => {
  const [row] = deriveSimHoldings({ A: { name: 'A', quantity: 1, avg_price: 5000 } }, { A: 5500 });
  assert.equal(row.price_known, true);
  assert.equal(row.pl_rate, 10);
});

test('avg_price가 없으면 price로 떨어진다 — 심마다 필드명이 다르다', () => {
  const [row] = deriveSimHoldings({ A: { name: 'A', quantity: 2, price: 1000 } }, { A: 1200 });
  assert.equal(row.avg_price, 1000);
  assert.equal(row.pl_rate, 20);
});

test('평단이 0이면 0으로 나누지 않는다', () => {
  const [row] = deriveSimHoldings({ A: { name: 'A', quantity: 1 } }, { A: 500 });
  assert.equal(row.pl_rate, 0);
});

test('portfolio가 없으면 빈 표다', () => {
  assert.deepEqual(deriveSimHoldings(null, null), []);
  assert.deepEqual(deriveSimHoldings(undefined, { A: 1 }), []);
});

// ── 누적 수익 ───────────────────────────────────────────────────────

test('누적 수익은 NAV에서 초기자본을 뺀 값이다', () => {
  assert.equal(computeNetPL({ total_asset: 3_150_000 }), 150_000);
  assert.equal(computeNetPL({ total_asset: 2_900_000 }), -100_000);
});

test('total_asset이 없으면 cash가 NAV다 — 보유가 없는 심은 그게 전부다', () => {
  assert.equal(computeNetPL({ cash: SIM_INITIAL_CASH }), 0);
});

test('stats.profit이 있으면 그걸 그대로 쓴다 — 리셋 예수금이 300만이 아니어도 맞다', () => {
  assert.equal(computeNetPL({ profit: -1234, total_asset: 2_900_000 }), -1234);
  assert.equal(computeNetPL({ profit: 0, total_asset: 2_000_000 }), 0);
});

test('심 전체가 300만으로 출발한다', () => {
  assert.equal(SIM_INITIAL_CASH, 3_000_000);
});

// ── 금일 거래 종목수 ────────────────────────────────────────────────

const HIST = [
  { type: 'sim_psych', time: '2026-07-30 09:10:00', symbol: '삼성전자(005930)' },
  { type: 'sim_psych', time: '2026-07-30 14:20:00', symbol: '삼성전자(005930)' },
  { type: 'sim_psych', time: '2026-07-30 14:25:00', symbol: 'SK하이닉스(000660)' },
  { type: 'sim_psych', time: '2026-07-29 10:00:00', symbol: '카카오(035720)' },
  { type: 'sim_bull', time: '2026-07-30 10:00:00', symbol: '네이버(035420)' },
];

test('같은 종목을 두 번 매매해도 한 종목이다', () => {
  assert.equal(countTodayTickers(HIST, 'sim_psych', '2026-07-30'), 2);
});

test('다른 심의 거래와 어제 거래는 세지 않는다', () => {
  assert.equal(countTodayTickers(HIST, 'sim_bull', '2026-07-30'), 1);
  assert.equal(countTodayTickers(HIST, 'sim_psych', '2026-07-29'), 1);
});

test('time이 없는 행이 섞여도 죽지 않는다', () => {
  const dirty = [...HIST, { type: 'sim_psych', symbol: '없음' }];
  assert.equal(countTodayTickers(dirty, 'sim_psych', '2026-07-30'), 2);
});

test('KST 날짜는 서버 시간대와 무관하다 — UTC 자정 뒤는 이미 한국의 다음 날이다', () => {
  // 2026-07-30 15:30 UTC = 2026-07-31 00:30 KST
  assert.equal(todayKST(new Date('2026-07-30T15:30:00Z')), '2026-07-31');
  assert.equal(todayKST(new Date('2026-07-30T05:00:00Z')), '2026-07-30');
});
