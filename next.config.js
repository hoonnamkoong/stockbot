/** @type {import('next').NextConfig} */

/**
 * 보안 헤더. 2026-09-10까지 이 파일은 비어 있었고 응답에 붙는 것은 Vercel이 주는
 * HSTS 하나뿐이었다.
 *
 * **CSP는 넣지 않았다.** Mantine이 인라인 스타일을 쓰고 Next가 인라인 스크립트를
 * 넣어서, 제대로 하려면 nonce 배선까지 가야 한다. 반쯤 넣은 CSP는 화면을 깨거나
 * `unsafe-inline`으로 열려 아무것도 못 막는다 — 둘 다 지금 얻는 것보다 비용이 크다.
 * 필요해지면 그때 nonce까지 같이 할 것.
 */
const securityHeaders = [
    // 클릭재킹. 세션 쿠키가 SameSite=Lax라 교차 사이트 iframe엔 애초에 쿠키가
    // 안 실리지만(그래서 `/trade`를 끼워도 로그인 화면이 뜬다), 그건 쿠키 정책에
    // 기댄 방어다. 프레임 자체를 막는 것이 한 겹 더다.
    { key: 'X-Frame-Options', value: 'DENY' },
    // 응답을 브라우저가 다른 타입으로 추측하지 못하게 한다.
    { key: 'X-Content-Type-Options', value: 'nosniff' },
    // 관리자 화면 주소가 외부 사이트의 Referer로 새지 않게 한다.
    { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
];

const nextConfig = {
    async headers() {
        return [{ source: '/:path*', headers: securityHeaders }];
    },
};

module.exports = nextConfig;
