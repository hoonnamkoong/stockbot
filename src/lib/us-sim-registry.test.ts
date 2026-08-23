import { test } from 'node:test';
import assert from 'node:assert';
import { US_SIM_REGISTRY } from './us-sim-registry.generated.ts';

test('US_SIM_REGISTRY has us_sim1 with USD currency', () => {
  assert.equal(US_SIM_REGISTRY.length, 1);
  const s = US_SIM_REGISTRY[0];
  assert.equal(s.id, 'us_sim1_minervini');
  assert.equal(s.uiKey, 'us_sim1');
  assert.equal(s.currency, 'USD');
  assert.equal(s.stateFile, 'sim_us1minervini_state.json');
  assert.equal(s.tradeable, false);
});
