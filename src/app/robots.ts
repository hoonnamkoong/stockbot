import type { MetadataRoute } from 'next';

/**
 * **색인 대상은 공개 쇼케이스(`/`) 하나뿐이다.** 나머지는 전부 로그인 뒤에 있다.
 *
 * `/login`은 클라이언트 컴포넌트라 `export const metadata`를 못 쓴다 — 그래서
 * noindex를 여기서 준다. 검색에서 가리는 것이 방어는 아니다(로그인 자체는
 * `src/lib/login-auth.ts`가 지킨다). 포트폴리오 방문자가 검색 결과에서
 * 관리자 로그인 화면을 먼저 보는 일이 없게 하려는 것이다.
 */
export default function robots(): MetadataRoute.Robots {
    return {
        rules: {
            userAgent: '*',
            allow: '/',
            disallow: ['/trade', '/research', '/login'],
        },
    };
}
