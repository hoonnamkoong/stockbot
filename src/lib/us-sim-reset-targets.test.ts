import { test } from 'node:test';
import assert from 'node:assert';
import { US_RESET_TARGETS, validateUsCash } from './us-sim-reset-targets.ts';

test('US_RESET_TARGETS는 등록된 US 심 전부를 포함한다', () => {
  assert.equal(US_RESET_TARGETS.length, 3);
  assert.equal(US_RESET_TARGETS[0].id, 'us_sim1');
  assert.equal(US_RESET_TARGETS[0].stateFile, 'sim_us1minervini_state.json');
  assert.equal(US_RESET_TARGETS[1].id, 'us_sim2');
  assert.equal(US_RESET_TARGETS[1].stateFile, 'sim_us2donchian_state.json');
  assert.equal(US_RESET_TARGETS[2].id, 'us_sim3');
  assert.equal(US_RESET_TARGETS[2].stateFile, 'sim_us3liquidity_state.json');
});

test('validateUsCash 경계값', () => {
  assert.equal(validateUsCash(20000).ok, true);
  assert.equal(validateUsCash(1000).ok, true);
  assert.equal(validateUsCash(500000).ok, true);
  assert.equal(validateUsCash(999).ok, false);
  assert.equal(validateUsCash(500001).ok, false);
  assert.equal(validateUsCash(20000.5).ok, false);
  assert.equal(validateUsCash('20000').ok, false);
});
