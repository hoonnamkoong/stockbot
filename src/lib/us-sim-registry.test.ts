import { test } from 'node:test';
import assert from 'node:assert';
import { US_SIM_REGISTRY } from './us-sim-registry.generated.ts';

test('US_SIM_REGISTRY has us_sim1 with USD currency', () => {
  assert.equal(US_SIM_REGISTRY.length, 3);
  const s = US_SIM_REGISTRY[0];
  assert.equal(s.id, 'us_sim1_minervini');
  assert.equal(s.uiKey, 'us_sim1');
  assert.equal(s.currency, 'USD');
  assert.equal(s.stateFile, 'sim_us1minervini_state.json');
  assert.equal(s.tradeable, false);
});

test('US_SIM_REGISTRY has us_sim2 with USD currency', () => {
  const s = US_SIM_REGISTRY.find((e) => e.id === 'us_sim2_donchian');
  assert.ok(s, 'us_sim2_donchian이 레지스트리에 없다');
  assert.equal(s.uiKey, 'us_sim2');
  assert.equal(s.currency, 'USD');
  assert.equal(s.stateFile, 'sim_us2donchian_state.json');
  assert.equal(s.tradeable, false);
});

test('US_SIM_REGISTRY has us_sim3 baseline sim', () => {
  const s = US_SIM_REGISTRY.find((e) => e.id === 'us_sim3_liquidity');
  assert.ok(s, 'us_sim3_liquidity가 레지스트리에 없다');
  assert.equal(s.uiKey, 'us_sim3');
  assert.equal(s.currency, 'USD');
  assert.equal(s.stateFile, 'sim_us3liquidity_state.json');
  assert.equal(s.tradeable, false);
});
