import { test } from 'node:test';
import assert from 'node:assert';
import { validateSimStateType, validateMonthParam } from './url-param-validation.ts';

test('validateSimStateType: 등록된 심은 통과한다', () => {
    // SIM_REGISTRY의 sim_psych → stateFile sim_psych_state.json → type='psych'
    assert.equal(validateSimStateType('psych').ok, true);
    // ANALYZERS의 sim0_libero → stateFile sim_libero_state.json → type='libero'
    assert.equal(validateSimStateType('libero').ok, true);
});

test('validateSimStateType: 경로 이탈은 막는다', () => {
    assert.equal(validateSimStateType('../..').ok, false);
    assert.equal(validateSimStateType('../../etc/passwd').ok, false);
    assert.equal(validateSimStateType('psych/../../../secret').ok, false);
});

test('validateSimStateType: 빈 값·등록부에 없는 값은 막는다', () => {
    assert.equal(validateSimStateType('').ok, false);
    // 은퇴한 구 심 이름 — 지금 SIM_REGISTRY에는 없다.
    assert.equal(validateSimStateType('original').ok, false);
    assert.equal(validateSimStateType('aggressive').ok, false);
    assert.equal(validateSimStateType('nope').ok, false);
});

test('validateMonthParam: YYYY-MM만 통과한다', () => {
    assert.equal(validateMonthParam('2026-09').ok, true);
    assert.equal(validateMonthParam('2026-01').ok, true);
    assert.equal(validateMonthParam('2026-12').ok, true);
});

test('validateMonthParam: 경로 이탈·형식 오류는 막는다', () => {
    assert.equal(validateMonthParam('../..').ok, false);
    assert.equal(validateMonthParam('2026-13').ok, false);
    assert.equal(validateMonthParam('2026-00').ok, false);
    assert.equal(validateMonthParam('2026-9').ok, false);
    assert.equal(validateMonthParam('2026/09').ok, false);
    assert.equal(validateMonthParam('').ok, false);
});
