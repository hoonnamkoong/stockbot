import { test } from 'node:test';
import assert from 'node:assert';
import { computeTurnPnl, basisFromPositions, type ProgramTurn, type ProgramPosition } from './program-turn.ts';

// 실전 프로그램 매매의 턴 손익을 그리는 계산이다. 화면에만 쓰이지만 사용자가 이 숫자를
// 보고 프로그램을 끄고 켠다. 파이썬 짝(program_turn.py)에는 tests/test_program_turn.py가
// 있는데 이쪽에는 없었다 — 계약이 주석에만 있고 지키는 것이 없는 상태였다.

const turn = (over: Partial<ProgramTurn> = {}): ProgramTurn => ({
  id: 't1', capital: 3_000_000, basis: {}, by_tag: {}, active_tag: null, ...over,
});

const pos = (over: Partial<ProgramPosition> = {}): ProgramPosition => ({
  name: '삼성전자', quantity: 10, avg_price: 1000, ...over,
});

test('턴이 없으면 0원이 아니라 빈 결과', () => {
  assert.deepEqual(computeTurnPnl(null, {}, {}), { pnl: 0, byTag: {} });
  assert.deepEqual(computeTurnPnl(undefined, {}, {}), { pnl: 0, byTag: {} });
  // id가 빈 문자열인 턴은 열린 적 없는 턴이다(파이썬 new_turn이 항상 id를 넣는다).
  assert.deepEqual(computeTurnPnl(turn({ id: '' }), {}, {}), { pnl: 0, byTag: {} });
});

test('보유가 없으면 확정분(by_tag)이 그대로 턴 손익', () => {
  const r = computeTurnPnl(turn({ by_tag: { sim4_bull_daytrading: 500 } }), {}, {});
  assert.deepEqual(r, { pnl: 500, byTag: { sim4_bull_daytrading: 500 } });
});

test('미실현은 종목의 tag에 귀속된다 — active_tag보다 우선', () => {
  // 파이썬 record_sell과 같은 기준이어야 한다. switch_tag가 시세를 못 구한 종목을
  // 직전 태그에 남겨두므로, 표시도 pos.tag를 따라가야 SIM별 분해가 엇갈리지 않는다.
  const r = computeTurnPnl(
    turn({ basis: { '005930': 1000 }, active_tag: 'sim5_sideways' }),
    { '005930': pos({ quantity: 10, tag: 'sim4_bull_daytrading' }) },
    { '005930': 1100 },
  );
  assert.deepEqual(r.byTag, { sim4_bull_daytrading: 1000 });
  assert.equal(r.pnl, 1000);
});

test('종목에 tag가 없으면 active_tag, 그것도 없으면 unknown', () => {
  const base = { basis: { '005930': 1000 } };
  const positions = { '005930': pos({ quantity: 10 }) };
  const prices = { '005930': 1100 };

  const withActive = computeTurnPnl(turn({ ...base, active_tag: 'sim6_bear' }), positions, prices);
  assert.deepEqual(withActive.byTag, { sim6_bear: 1000 });

  const withNeither = computeTurnPnl(turn({ ...base, active_tag: null }), positions, prices);
  assert.deepEqual(withNeither.byTag, { unknown: 1000 });
});

test('기준가 0은 현재가로 폴백한다 — ??였다면 시가총액 전체가 수익이 된다', () => {
  // program-turn.ts의 `||` 폴백이 지키는 것. `??`로 바꾸면 0을 통과시켜
  // (1100 - 0) * 10 = 11,000원이 턴 수익으로 계상된다. 실제로는 기여 0이 맞다.
  const r = computeTurnPnl(
    turn({ basis: { '005930': 0 }, active_tag: 'sim4_bull_daytrading' }),
    { '005930': pos({ quantity: 10 }) },
    { '005930': 1100 },
  );
  assert.equal(r.pnl, 0);
  assert.notEqual(r.pnl, 11_000);
});

test('기준가가 없는 종목도 현재가 폴백 → 기여 0', () => {
  // 매수 직후 원장에 basis가 아직 안 실린 구간. 없는 것을 0으로 읽어
  // 매수액 전체를 수익으로 부풀리지 않아야 한다.
  const r = computeTurnPnl(
    turn({ basis: {}, active_tag: 'sim4_bull_daytrading' }),
    { '005930': pos({ quantity: 10 }) },
    { '005930': 1100 },
  );
  assert.equal(r.pnl, 0);
});

test('시세를 못 구한 종목은 건너뛴다 — 0원으로 계상하지 않는다', () => {
  const t = turn({ basis: { '005930': 1000 }, by_tag: { sim6_bear: 700 }, active_tag: 'sim6_bear' });
  const positions = { '005930': pos({ quantity: 10 }) };

  // 시세 자체가 없음
  assert.deepEqual(computeTurnPnl(t, positions, {}).byTag, { sim6_bear: 700 });
  // 0 / 음수 / 숫자가 아닌 값 — 전부 '못 구함'이다
  assert.deepEqual(computeTurnPnl(t, positions, { '005930': 0 }).byTag, { sim6_bear: 700 });
  assert.deepEqual(computeTurnPnl(t, positions, { '005930': -1 }).byTag, { sim6_bear: 700 });
  assert.deepEqual(
    computeTurnPnl(t, positions, { '005930': NaN as number }).byTag, { sim6_bear: 700 });
});

test('확정분과 미실현이 같은 태그에서 합쳐진다', () => {
  const r = computeTurnPnl(
    turn({ basis: { '005930': 1000 }, by_tag: { sim4_bull_daytrading: 500 } }),
    { '005930': pos({ quantity: 10, tag: 'sim4_bull_daytrading' }) },
    { '005930': 1100 },
  );
  assert.deepEqual(r.byTag, { sim4_bull_daytrading: 1500 });
  assert.equal(r.pnl, 1500);
});

test('손실도 그대로 반영된다', () => {
  const r = computeTurnPnl(
    turn({ basis: { '005930': 1000 }, active_tag: 'sim5_sideways' }),
    { '005930': pos({ quantity: 10 }) },
    { '005930': 900 },
  );
  assert.equal(r.pnl, -1000);
});

test('여러 종목이 태그별로 분해되고 pnl은 그 합', () => {
  const r = computeTurnPnl(
    turn({ basis: { '005930': 1000, '000660': 2000 } }),
    {
      '005930': pos({ quantity: 10, tag: 'sim4_bull_daytrading' }),
      '000660': pos({ quantity: 5, tag: 'sim5_sideways' }),
    },
    { '005930': 1100, '000660': 1800 },
  );
  assert.deepEqual(r.byTag, { sim4_bull_daytrading: 1000, sim5_sideways: -1000 });
  assert.equal(r.pnl, 0);
});

test('원장의 by_tag를 변조하지 않는다 — 폴링으로 반복 호출되는 함수다', () => {
  // 프론트가 주기적으로 다시 그린다. 원본을 제자리 수정하면 호출할 때마다
  // 미실현이 확정분에 누적돼 손익이 계속 불어난다.
  const t = turn({ basis: { '005930': 1000 }, by_tag: { sim6_bear: 500 }, active_tag: 'sim6_bear' });
  const positions = { '005930': pos({ quantity: 10 }) };
  const prices = { '005930': 1100 };

  const first = computeTurnPnl(t, positions, prices);
  const second = computeTurnPnl(t, positions, prices);

  assert.deepEqual(first, second);
  assert.deepEqual(t.by_tag, { sim6_bear: 500 }, '원본 by_tag가 변했다');
});

test('턴 기준가는 매입 평단이다 — ON 시점 시세로 리셋하지 않는다', () => {
  // 파이썬 new_turn과 같은 규칙. 갈리면 파이썬 첫 런 전후로 턴 손익이 점프한다.
  const positions = {
    A: { name: '가', quantity: 10, avg_price: 1000 },
    B: { name: '나', quantity: 5, avg_price: 2000 },
  };
  assert.deepEqual(basisFromPositions(positions), { A: 1000, B: 2000 });
});

test('평단이 없거나 0인 종목은 기준가를 만들지 않는다', () => {
  // 0을 넣으면 (현재가 - 0) * 수량 = 시가총액 전체가 턴 수익이 된다.
  const positions = { A: { name: '가', quantity: 10, avg_price: 0 } } as any;
  assert.deepEqual(basisFromPositions(positions), {});
});

test('보유가 없으면 빈 기준가다', () => {
  assert.deepEqual(basisFromPositions({}), {});
});
