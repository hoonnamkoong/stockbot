import { test } from 'node:test';
import assert from 'node:assert';
import { RESET_TARGETS, RESET_CSV_HEADER, buildResetState, validateCash } from './sim-reset-targets.ts';

// 매니페스트와의 대조는 tests/test_sim_registry_consistency.py가 한다(pytest 스위트에서
// 실제로 돌아간다). 여기서는 목록 자체의 형식 불변식만 본다 — 개수를 박아두면
// 심을 추가할 때 이 테스트가 오히려 누락을 고정한다(2026-07-29 실제로 그랬다:
// length === 9가 심8·심9·심9-1 누락을 지키고 있었다).
test('심 목록 형식 규칙', () => {
  const ids = RESET_TARGETS.map(t => t.id);
  assert.equal(new Set(ids).size, ids.length, 'id 중복');
  for (const t of RESET_TARGETS) {
    assert.match(t.stateFile, /^sim_[a-z0-9]+_state\.json$/);
    assert.match(t.csvFile, /^trade_history_sim_[a-z0-9]+\.csv$/);
    // 상태 파일과 CSV는 같은 심 이름에서 파생된다(BaseSimulator 규칙).
    const name = t.stateFile.slice('sim_'.length, -'_state.json'.length);
    assert.equal(t.csvFile, `trade_history_sim_${name}.csv`);
  }
  const bear = RESET_TARGETS.find(t => t.id === 'sim6')!;
  assert.equal(bear.stateFile, 'sim_bear_state.json');
});

test('CSV 헤더는 BOM + 정확한 컬럼', () => {
  assert.equal(RESET_CSV_HEADER, '﻿timestamp,symbol,action,price,quantity,total_amount,reason\n');
});

test('buildResetState는 reset_state shape', () => {
  const s: any = buildResetState(3_000_000);
  assert.equal(s.initial_cash, 3_000_000);
  assert.equal(s.cash, 3_000_000);
  assert.equal(s.peak_nav, 3_000_000);
  assert.equal(s.invested, 0);
  assert.equal(s.total_fees, 0);
  assert.deepEqual(s.portfolio, {});
  assert.deepEqual(s.history, [3_000_000]);
  assert.deepEqual(s.daily_trades, []);
  assert.equal(s.market_index_healthy, true);
  assert.deepEqual(s.cooldown_codes, {});
});

test('validateCash 경계값', () => {
  assert.equal(validateCash(3_000_000).ok, true);
  assert.equal(validateCash(100_000).ok, true);
  assert.equal(validateCash(1_000_000_000).ok, true);
  assert.equal(validateCash(99_999).ok, false);
  assert.equal(validateCash(1_000_000_001).ok, false);
  assert.equal(validateCash(3_000_000.5).ok, false);
  assert.equal(validateCash('3000000').ok, false);
  assert.equal(validateCash(NaN).ok, false);
});
