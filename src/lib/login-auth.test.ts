import { test } from 'node:test';
import assert from 'node:assert';
import { authorizeLogin, nextLockState } from './login-auth.ts';

// 로그인 화면이 공개되면 이 판정이 인터넷에 노출된다. 지금까지는 사이트 전체가
// 로그인 뒤에 있어 `/login`이 발견될 일이 없었다 — 방어가 아니라 무명이었다.

const NOW = Date.parse('2026-09-09T10:00:00+09:00');

const BASE = {
  password: 'correct-horse',
  deviceId: 'dev-1',
  adminPassword: 'correct-horse',
  trustedDevices: 'dev-1, dev-2',
  lockedUntil: null as string | null,
  now: NOW,
};

test('비밀번호와 신뢰 디바이스가 둘 다 맞으면 통과', () => {
  assert.deepEqual(authorizeLogin(BASE), { ok: true });
});

test('공백이 섞인 TRUSTED_DEVICES도 파싱한다', () => {
  assert.deepEqual(authorizeLogin({ ...BASE, deviceId: 'dev-2' }), { ok: true });
});

test('비밀번호가 틀린 것과 디바이스가 틀린 것이 같은 이유다 — 오라클을 주지 않는다', () => {
  const wrongPassword = authorizeLogin({ ...BASE, password: 'nope' });
  const wrongDevice = authorizeLogin({ ...BASE, deviceId: 'attacker-uuid' });
  assert.equal(wrongPassword.reason, 'rejected');
  assert.equal(wrongDevice.reason, 'rejected');
});

// deviceTrusted는 호출자 전용이다 — 잠금 카운터를 올릴지만 정하고 응답에는 안 실린다.

test('모르는 디바이스의 실패는 카운터를 올리지 않는다 — 주인을 잠글 수 없다', () => {
  const v = authorizeLogin({ ...BASE, password: 'nope', deviceId: 'attacker-uuid' });
  assert.deepEqual(v, { ok: false, reason: 'rejected', deviceTrusted: false });
});

test('신뢰 디바이스에서 비밀번호만 틀리면 카운터를 올린다 — 이게 실제로 뚫릴 수 있는 경우다', () => {
  const v = authorizeLogin({ ...BASE, password: 'nope' });
  assert.deepEqual(v, { ok: false, reason: 'rejected', deviceTrusted: true });
});

test('비밀번호를 맞혀도 디바이스가 아니면 통과가 아니다', () => {
  const v = authorizeLogin({ ...BASE, deviceId: 'attacker-uuid' });
  assert.equal(v.ok, false);
});

test('ADMIN_PASSWORD가 없으면 통과가 아니라 misconfigured — 빈 값이 만능 열쇠가 되면 안 된다', () => {
  const v = authorizeLogin({ ...BASE, adminPassword: undefined, password: '' });
  assert.deepEqual(v, { ok: false, reason: 'misconfigured' });
});

test('TRUSTED_DEVICES가 비어 있으면 misconfigured', () => {
  assert.deepEqual(authorizeLogin({ ...BASE, trustedDevices: '' }), { ok: false, reason: 'misconfigured' });
  assert.deepEqual(authorizeLogin({ ...BASE, trustedDevices: ' , , ' }), { ok: false, reason: 'misconfigured' });
});

test('잠겨 있으면 자격증명이 맞아도 막고 남은 분을 준다', () => {
  const v = authorizeLogin({
    ...BASE,
    lockedUntil: new Date(NOW + 7 * 60000).toISOString(),
  });
  assert.deepEqual(v, { ok: false, reason: 'locked', retryAfterMin: 7 });
});

test('잠금이 지났으면 다시 통과한다', () => {
  const v = authorizeLogin({
    ...BASE,
    lockedUntil: new Date(NOW - 60000).toISOString(),
  });
  assert.deepEqual(v, { ok: true });
});

test('망가진 잠금 시각은 잠금으로 치지 않는다 — 파싱 실패로 스스로를 영구 차단하면 안 된다', () => {
  assert.deepEqual(authorizeLogin({ ...BASE, lockedUntil: 'garbage' }), { ok: true });
});

// --- 잠금 카운터 ---

test('임계 전에는 카운터만 오르고 잠기지 않는다', () => {
  const s = nextLockState({ fails: 2, lockedUntil: null, maxAttempts: 5, lockoutMin: 10, now: NOW });
  assert.deepEqual(s, { fails: 3, locked_until: null });
});

test('임계에 닿으면 잠기고 카운터는 0으로 돌아간다', () => {
  const s = nextLockState({ fails: 4, lockedUntil: null, maxAttempts: 5, lockoutMin: 10, now: NOW });
  assert.equal(s.fails, 0);
  assert.equal(s.locked_until, new Date(NOW + 10 * 60000).toISOString());
});
