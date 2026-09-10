/**
 * **미들웨어가 세션 없이 통과시키는 경로 목록.** 여기 없으면 막힌다.
 *
 * ## 왜 뒤집었나 (2026-09-10)
 *
 * 그전까지 미들웨어는 매처에 적힌 네 경로(`/trade`·`/research`)만 막았다.
 * 즉 **새로 만든 라우트는 기본이 공개**였고, API 26개는 매처 밖이라 각자
 * 검사했다 — 그중 12개가 무인증이었다.
 *
 * 2026-09-09 아침에 실계좌 잔고와 실체결이 인증 없이 나간 것이 정확히 이 구조다.
 * 한 라우트를 고치는 것으로는 같은 사고가 또 난다. 새 라우트가 **기본으로 막히면**
 * 실수의 방향이 "안 열림"이 되고, 그건 화면이 안 뜨는 것으로 즉시 드러난다.
 *
 * ## 목록을 손으로 유지하는 것은 그대로다 — 다만 방향이 반대다
 *
 * 빠뜨리면 공개면이 비거나 매매가 멈춘다(시끄럽다). 예전엔 빠뜨리면 조용히
 * 새어 나갔다. `route-access.test.ts`가 스스로 검사하는 라우트와 이 목록을
 * **양방향으로** 비교한다.
 */

/** 공개면. 2026-09-09 저녁부터 `/` 한 장뿐이고 `/login`은 문이라 막을 수 없다. */
const PUBLIC_PAGES = [
    '/',
    '/login',
    '/robots.txt',      // src/app/robots.ts — 색인 규칙 자체가 막히면 안 된다
];

/** 공개 페이지가 그리는 데이터. ShowcaseClient의 fetch 세 개와 정확히 같다. */
const PUBLIC_APIS = [
    '/api/simulation/stats',
    '/api/trade/history',     // 세션 없으면 심 기록만 나간다(visibleTradeHistory)
    '/api/stocks/research',
    '/api/health',            // 정적 플래그만 반환한다 — 지킬 값이 없다
];

/**
 * **스스로 검사하는 경로.** 미들웨어가 세션을 요구하면 기계가 못 들어온다 —
 * 이들은 세션이 아니라 시크릿으로 인증한다. 통과시키는 것이지 무방비가 아니다.
 */
export const SELF_GUARDED_APIS = [
    '/api/auth',             // 로그인 자체. 막으면 들어갈 문이 없다(next-auth가 지킨다)
    '/api/cron',             // CRON_SECRET (smart-trigger 포함) — 태스커
    '/api/trade/ai/trigger', // CRON_SECRET
    '/api/trade/order',      // WEBHOOK_SECRET 또는 세션+PIN — 매매 루프
];

/**
 * `/api/auth`만 예외다 — next-auth가 자기 방식으로 지키고 시크릿 문자열이
 * 라우트 파일에 없다. 나머지는 **실제로 시크릿을 검사해야** 이 목록에 들어온다.
 *
 * 이 예외 목록이 따로 있는 이유: 처음 목록을 짤 때 `/api/stocks/refresh`를
 * "vercel.json cron이 부른다"는 이유로 여기 넣었는데, **그 라우트는 아무것도
 * 검사하지 않았다.** 배포 후 실측에서 무인증 200으로 드러났다(프로덕션에서는
 * `process.env.VERCEL` 검사로 403이라 하는 일도 없었다 — 이유 자체가 틀렸다).
 * "스스로 검사한다"는 라벨은 붙이는 것이 아니라 확인하는 것이다.
 */
export const SELF_GUARD_EXEMPT = ['/api/auth'];

const OPEN = [...PUBLIC_PAGES, ...PUBLIC_APIS, ...SELF_GUARDED_APIS];

/**
 * 세션 없이 통과하나. 접두사는 **경로 경계에서만** 맞는다 —
 * `/api/simulation/stats`가 `/api/simulation/stats-us`를 열어 주면 안 된다.
 */
export function isOpen(pathname: string): boolean {
    const p = pathname.length > 1 && pathname.endsWith('/')
        ? pathname.replace(/\/+$/, '')
        : pathname;
    return OPEN.some((o) => p === o || p.startsWith(o + '/'));
}
