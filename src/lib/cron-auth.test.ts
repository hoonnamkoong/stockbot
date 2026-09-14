import { test } from 'node:test';
import assert from 'node:assert';
import { authorizeCronRequest } from './cron-auth.ts';

// 태스커 → /api/cron·trade/ai/trigger가 실매매 워크플로를 깨우는 유일한 문이다.
// 헤더 우선, 쿼리스트링은 태스커 설정을 바꾸기 전까지 당분간 허용(경고와 함께).

const SECRET = 'super-secret-cron-value';

test('올바른 헤더면 통과하고 경고는 없다', () => {
  const v = authorizeCronRequest({
    authHeader: `Bearer ${SECRET}`,
    secretParam: null,
    cronSecret: SECRET,
  });
  assert.deepEqual(v, { ok: true, deprecated: false });
});

test('올바른 쿼리 시크릿이면 통과하되 deprecated 경고가 붙는다', () => {
  const v = authorizeCronRequest({
    authHeader: null,
    secretParam: SECRET,
    cronSecret: SECRET,
  });
  assert.deepEqual(v, { ok: true, deprecated: true });
});

test('헤더가 맞으면 쿼리가 있어도 경고 없이 헤더 경로로 통과한다', () => {
  const v = authorizeCronRequest({
    authHeader: `Bearer ${SECRET}`,
    secretParam: 'wrong-or-whatever',
    cronSecret: SECRET,
  });
  assert.deepEqual(v, { ok: true, deprecated: false });
});

test('헤더도 쿼리도 없으면 거부', () => {
  const v = authorizeCronRequest({ authHeader: null, secretParam: null, cronSecret: SECRET });
  assert.deepEqual(v, { ok: false });
});

test('헤더와 쿼리 둘 다 틀리면 거부', () => {
  const v = authorizeCronRequest({
    authHeader: 'Bearer nope',
    secretParam: 'nope-either',
    cronSecret: SECRET,
  });
  assert.deepEqual(v, { ok: false });
});

test('CRON_SECRET이 서버에 없으면 무엇을 보내도 무조건 거부된다', () => {
  for (const [authHeader, secretParam] of [
    [`Bearer ${SECRET}`, null],
    [null, SECRET],
    [`Bearer undefined`, 'undefined'],
    [null, null],
  ] as const) {
    const v = authorizeCronRequest({ authHeader, secretParam, cronSecret: undefined });
    assert.deepEqual(v, { ok: false }, `authHeader=${authHeader} secretParam=${secretParam} 가 통과했다`);
  }
});

test('CRON_SECRET이 빈 문자열이어도 거부된다', () => {
  const v = authorizeCronRequest({ authHeader: `Bearer `, secretParam: '', cronSecret: '' });
  assert.deepEqual(v, { ok: false });
});

test('길이가 다른 헤더 값으로도 예외 없이 거부된다 (timingSafeEqual 길이 함정)', () => {
  assert.doesNotThrow(() => {
    const v = authorizeCronRequest({ authHeader: 'Bearer x', secretParam: null, cronSecret: SECRET });
    assert.deepEqual(v, { ok: false });
  });
  assert.doesNotThrow(() => {
    const v = authorizeCronRequest({
      authHeader: `Bearer ${SECRET}extra-long-suffix-here`,
      secretParam: null,
      cronSecret: SECRET,
    });
    assert.deepEqual(v, { ok: false });
  });
});

test('길이가 다른 쿼리 시크릿으로도 예외 없이 거부된다', () => {
  assert.doesNotThrow(() => {
    const v = authorizeCronRequest({ authHeader: null, secretParam: 'x', cronSecret: SECRET });
    assert.deepEqual(v, { ok: false });
  });
  assert.doesNotThrow(() => {
    const v = authorizeCronRequest({
      authHeader: null,
      secretParam: SECRET + 'trailing-junk',
      cronSecret: SECRET,
    });
    assert.deepEqual(v, { ok: false });
  });
});

test('Bearer 접두사가 없으면 값이 같아도 통과하지 않는다', () => {
  const v = authorizeCronRequest({ authHeader: SECRET, secretParam: null, cronSecret: SECRET });
  assert.deepEqual(v, { ok: false });
});
