/**
 * 태스커(폰) → `/api/cron`, `/api/trade/ai/trigger`가 실매매 워크플로를 깨우는
 * 유일한 문이다. 둘 다 쿼리스트링 `?secret=`으로 CRON_SECRET을 받아 `!==`로
 * 비교하고 있었다 — URL은 접근 로그·프록시·Referer에 남는다.
 *
 * 헤더(`Authorization: Bearer <CRON_SECRET>`)를 우선으로 두되, 쿼리스트링은
 * 당분간 계속 허용한다. 태스커 설정을 사용자가 헤더로 바꾸기 전에 쿼리를
 * 끊으면 실매매가 멈춘다 — 그래서 쿼리 경로는 막지 않고 `deprecated: true`로
 * 표시만 한다. 호출부(라우트)가 이 플래그로 "헤더로 옮겨라" 경고를 로그에 남긴다.
 *
 * `trade-auth.ts`와 같은 이유로 순수 함수다: `app/api/**\/route.ts`는 `next/server`
 * 때문에 node --test로 import가 안 돼, 판정만 여기로 내리면 네트워크 없이 검증된다.
 */

import { timingSafeEqual } from 'node:crypto';

export type CronAuthVerdict =
  | { ok: true; deprecated: boolean }
  | { ok: false };

/** 길이가 달라도 예외 없이 상수시간으로 비교한다. timingSafeEqual은 버퍼 길이가
 *  다르면 곧장 throw하므로, 길이가 다를 때는 같은 길이의 더미와 비교해 시간을
 *  맞추고 항상 false를 반환한다. */
function timingSafeStringEqual(a: string, b: string): boolean {
  const bufA = Buffer.from(a, 'utf8');
  const bufB = Buffer.from(b, 'utf8');
  if (bufA.length !== bufB.length) {
    timingSafeEqual(bufA, bufA);
    return false;
  }
  return timingSafeEqual(bufA, bufB);
}

/**
 * cron 발화 요청의 인증 판정. CRON_SECRET이 서버에 없으면 무엇을 보내도
 * 무조건 거부(fail-closed) — 빈 시크릿을 폴백으로 두면 그 폴백이 곧
 * 실매매 비밀번호가 된다.
 */
export function authorizeCronRequest(input: {
  authHeader: string | null;
  secretParam: string | null;
  cronSecret: string | undefined;
}): CronAuthVerdict {
  const { authHeader, secretParam, cronSecret } = input;

  if (!cronSecret) return { ok: false };

  const expectedHeader = `Bearer ${cronSecret}`;
  if (authHeader !== null && timingSafeStringEqual(authHeader, expectedHeader)) {
    return { ok: true, deprecated: false };
  }

  if (secretParam !== null && timingSafeStringEqual(secretParam, cronSecret)) {
    return { ok: true, deprecated: true };
  }

  return { ok: false };
}
