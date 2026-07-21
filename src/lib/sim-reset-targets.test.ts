import { test } from 'node:test';
import assert from 'node:assert';
import { RESET_TARGETS, RESET_CSV_HEADER, buildResetState, validateCash } from './sim-reset-targets.ts';

test('대상 심 9개 + 파일명 규칙', () => {
  assert.equal(RESET_TARGETS.length, 9);
  const ids = RESET_TARGETS.map(t => t.id);
  assert.deepEqual(ids, ['sim1','sim2','sim3','sim4','sim4_daytrading','sim5','sim6','sim7','sim10']);
  const bear = RESET_TARGETS.find(t => t.id === 'sim6')!;
  assert.equal(bear.stateFile, 'sim_bear_state.json');
  assert.equal(bear.csvFile, 'trade_history_sim_bear.csv');
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
