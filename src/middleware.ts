import { withAuth } from "next-auth/middleware";

export default withAuth({
    pages: {
        signIn: '/login',
    },
});

/**
 * **여기 나열된 것만 막힌다.** 새 경로는 기본이 공개다 — 이 방식의 위험은
 * 2026-09-09에 실제로 드러났다(`/api/*`가 매처에 없어 실계좌 잔고와 실체결이
 * 인증 없이 나갔다). 돈을 만지는 API는 각자 세션을 검사하지만, 목록을 손으로
 * 유지하는 구조라는 사실은 그대로다. fail-closed로 뒤집는 것은 별건이다.
 *
 * `/research`는 2026-09-09에 **의도적으로** 빠졌다 — 공개 리서치 보드가 됐다.
 * 표는 누구나 보고, 조작 UI(퀵 주문·스크래퍼 제어·다운로드)는 ResearchClient가
 * 세션으로 가린다. 실거래 API는 여전히 각자 막혀 있다.
 */
export const config = { matcher: ["/trade", "/trade/:path*"] };
