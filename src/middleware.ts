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
 * **공개 페이지는 `/` 하나뿐이다.** 리서치 표는 그 페이지가 직접 그리고,
 * `/research`는 비공개로 되돌렸다(2026-09-09 저녁). 공개면을 한 장으로 두면
 * "이 주소는 공개인가"를 매번 따질 필요가 없고, 공개 화면에서 로그인 벽으로
 * 이어지는 링크도 생기지 않는다.
 */
export const config = {
    matcher: ["/trade", "/trade/:path*", "/research", "/research/:path*"],
};
