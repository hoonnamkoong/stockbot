/**
 * 실거래 문을 여는 두 판정 — 누가 주문할 수 있나(PIN), 무엇으로 무장할 수 있나(화이트리스트).
 *
 * 라우트 안에 있던 것을 그대로 옮겼다. `app/api/**\/route.ts`는 `next/server` 때문에
 * node 테스트가 import를 못 해서, 실거래를 다루는 TS 약 1,400줄에 테스트가 0이었다.
 * 순수한 판정만 여기로 내리면 네트워크 없이 전부 확인할 수 있다.
 *
 * 판정만 한다 — 세션 토큰을 얻는 것, 실패 횟수를 세는 것, 응답을 쓰는 것은 라우트 몫이다.
 */

export type AuthVerdict =
  | { ok: true }
  | { ok: false; status: 401 | 403 | 500; error: string };

/** PIN이 틀렸을 때와 세션이 없을 때 같은 문구를 준다 — 어느 쪽이 틀렸는지 알려주지 않는다. */
const AUTH_FAILED = 'Invalid TRADING AUTH';

/**
 * 수동 주문(`/api/trade/order`)의 인증 판정.
 *
 * 자동화 엔진은 웹훅 시크릿으로 들어온다. 사람은 **세션과 PIN을 둘 다** 통과해야 한다 —
 * PIN만으로 주문이 나가면 유출된 PIN 하나가 곧 주문 권한이 된다.
 *
 * TRADE_PIN이 서버에 없으면 통과가 아니라 500이다. 폴백 PIN을 두면 그 폴백이 곧
 * 실거래 비밀번호가 된다.
 */
export function authorizeManualOrder(input: {
  authHeader: string | null;
  webhookSecret: string | undefined;
  hasSession: boolean;
  pin: unknown;
  tradePin: string | undefined;
}): AuthVerdict {
  const { authHeader, webhookSecret, hasSession, pin, tradePin } = input;

  if (webhookSecret && authHeader === `Bearer ${webhookSecret}`) return { ok: true };
  if (!hasSession) return { ok: false, status: 401, error: AUTH_FAILED };
  if (!tradePin) return { ok: false, status: 500, error: 'Server auth not configured' };
  if (pin !== tradePin) return { ok: false, status: 403, error: AUTH_FAILED };
  return { ok: true };
}

/**
 * 비인증 요청이 받아 갈 매매 기록. **세션이 없으면 심(sim)만 나간다.**
 *
 * 2026-09-09에 `/api/trade/history`가 파라미터와 무관하게 실체결과 심 기록을
 * 항상 합쳐서, 인증 없이 반환하고 있었다. 미들웨어 매처가 페이지만 잡고
 * `/api/*`를 잡지 않는데 라우트에도 검사가 없었다. 안 터진 이유는 방어가 아니라
 * URL이 안 알려져서였다.
 *
 * 라우트가 세션 없을 때 실거래를 **애초에 조회하지 않는데도** 이 함수가 한 번 더
 * 거르는 이유: 조회 조건과 노출 조건이 갈라지는 것이 이 사고의 모양이었다.
 * 둘 중 하나만 남으면 다음 수정에서 또 갈라진다.
 */
export function visibleTradeHistory<T>(input: {
  hasSession: boolean;
  real: T[];
  sim: T[];
}): T[] {
  return input.hasSession ? [...input.real, ...input.sim] : [...input.sim];
}

export type ArmVerdict =
  | { ok: true; sim: string; budget: number }
  | { ok: false; error: string };

/**
 * 프로그램 매매 ON(arm) 요청의 판정. **fail-closed** — 유효한 심과 예산(>0)이 둘 다
 * 있을 때만 켜진다.
 *
 * 심 id는 화이트리스트(매니페스트의 tradeable) 안에 있어야 한다. 임의의 id로 켜지면
 * 파이썬이 모르는 심 이름이 설정에 박혀, 화면은 ON인데 아무것도 안 도는 상태가 된다.
 * 예산은 내림한 정수로 정규화한다(소수점 예산으로 사이징이 흔들리지 않게).
 */
export function validateArmRequest(input: {
  selectedSim: unknown;
  budget: unknown;
  tradeableIds: Iterable<string>;
}): ArmVerdict {
  const valid = new Set(input.tradeableIds);
  const sim = typeof input.selectedSim === 'string' && valid.has(input.selectedSim)
    ? input.selectedSim
    : null;
  const budget = Math.max(0, Math.floor(Number(input.budget) || 0));

  if (!sim) return { ok: false, error: '유효한 매매 심을 선택해야 켤 수 있습니다.' };
  if (budget <= 0) return { ok: false, error: '프로그램 예산(>0)을 설정해야 켤 수 있습니다.' };
  return { ok: true, sim, budget };
}
