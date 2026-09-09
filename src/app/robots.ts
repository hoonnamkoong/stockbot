import type { MetadataRoute } from 'next';

/**
 * 공개 쇼케이스(`/`)와 리서치 보드(`/research`)만 색인 대상이다.
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
            disallow: ['/trade', '/login'],
        },
    };
}
