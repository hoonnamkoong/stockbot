/**
 * 대시보드 로그인의 판정 — 잠겨 있나, 이 자격증명이 맞나.
 *
 * 판정만 한다. 잠금 상태를 읽고 쓰는 것, 세션을 만드는 것은 라우트 몫이다.
 * `trade-auth.ts`와 같은 이유로 여기 있다 — `app/api/**\/route.ts`는 `next/server`
 * 때문에 node 테스트가 import를 못 한다.
 *
 * **문구는 하나다.** 원래 authorize()는 비밀번호가 틀리면 "Invalid password",
 * 맞고 디바이스가 안 맞으면 "Device Not Allowed"를 던졌다. 그 차이가 곧
 * "비밀번호는 맞혔다"는 신호라, 무차별 대입에 정답 확인용 오라클을 준다.
 * 로그인 화면이 공개되면 이게 실제로 시험받는다. `trade-auth.ts`가 주문
 * 경로에 이미 세워둔 원칙(어느 쪽이 틀렸는지 알려주지 않는다)을 여기도 적용한다.
 */

export type LoginVerdict =
  | { ok: true }
  | { ok: false; reason: 'locked'; retryAfterMin: number }
  /**
   * `deviceTrusted`는 **호출자만 본다** — 잠금 카운터를 올릴지 정하는 데만 쓰고
   * 절대 응답에 싣지 않는다. 오라클은 공격자가 보는 것에 대한 문제다.
   *
   * 이 값이 필요한 이유: 카운터가 전역이면 공개된 `/login`에 아무나 5번 틀려서
   * **주인을 영구 잠금**시킬 수 있다(계속 틀리면 잠금이 계속 갱신된다). 신뢰
   * 디바이스에서 온 실패만 세면 그 공격이 성립하지 않는다. 모르는 디바이스는
   * 애초에 비밀번호를 맞혀도 못 들어오므로, 그쪽을 세는 것은 방어가 아니라
   * 자해다.
   */
  | { ok: false; reason: 'rejected'; deviceTrusted: boolean }
  | { ok: false; reason: 'misconfigured' };

/**
 * 서버에 ADMIN_PASSWORD나 TRUSTED_DEVICES가 없으면 **통과가 아니라 misconfigured**다.
 * 둘 중 하나라도 비면 남은 한 겹만으로 문이 열리고, 빈 값이 곧 만능 열쇠가 된다.
 */
export function authorizeLogin(input: {
  password: unknown;
  deviceId: unknown;
  adminPassword: string | undefined;
  trustedDevices: string | undefined;
  lockedUntil: string | null;
  now: number;
}): LoginVerdict {
  const { password, deviceId, adminPassword, trustedDevices, lockedUntil, now } = input;

  if (lockedUntil) {
    const until = Date.parse(lockedUntil);
    if (!Number.isNaN(until) && now < until) {
      return { ok: false, reason: 'locked', retryAfterMin: Math.ceil((until - now) / 60000) };
    }
  }

  if (!adminPassword || !trustedDevices) return { ok: false, reason: 'misconfigured' };

  const allowed = trustedDevices.split(',').map((d) => d.trim()).filter(Boolean);
  if (allowed.length === 0) return { ok: false, reason: 'misconfigured' };

  // 비밀번호와 디바이스를 **함께** 본다. 먼저 비밀번호로 끊으면 그 시점의 응답이
  // 곧 정답 신호가 된다.
  const passwordOk = typeof password === 'string' && password === adminPassword;
  const deviceOk = typeof deviceId === 'string' && allowed.includes(deviceId);
  if (!passwordOk || !deviceOk) return { ok: false, reason: 'rejected', deviceTrusted: deviceOk };

  return { ok: true };
}

/**
 * 실패 1건을 반영한 다음 잠금 상태. 임계에 닿으면 카운터를 0으로 되돌리고
 * 잠금 시각을 넣는다(잠긴 동안 카운터를 또 올릴 필요가 없다 — 어차피 막힌다).
 */
export function nextLockState(input: {
  fails: number;
  lockedUntil: string | null;
  maxAttempts: number;
  lockoutMin: number;
  now: number;
}): { fails: number; locked_until: string | null } {
  const fails = input.fails + 1;
  if (fails >= input.maxAttempts) {
    return { fails: 0, locked_until: new Date(input.now + input.lockoutMin * 60000).toISOString() };
  }
  return { fails, locked_until: input.lockedUntil };
}
