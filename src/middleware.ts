import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { getToken } from 'next-auth/jwt';
import { isOpen } from '@/lib/route-access';

/**
 * **기본은 막힘이다.** 통과 목록은 `src/lib/route-access.ts`에 있고 그 파일이
 * 왜 열려 있는지를 항목마다 적는다.
 *
 * 2026-09-10까지 이 파일은 반대였다 — 매처에 적은 네 경로만 막고 나머지는 전부
 * 공개. 새 라우트가 기본 공개라는 뜻이었고, 09-09 아침 실계좌 유출이 그 구조에서
 * 나왔다. 방향을 뒤집으면 실수가 "안 열림"으로 드러난다(화면이 비면 바로 보인다).
 *
 * **API는 리다이렉트하지 않는다.** 파이썬 호출부가 307을 따라가면 로그인 화면
 * HTML을 200으로 받아 "성공"으로 읽는다. 401 JSON이어야 호출부가 실패로 안다.
 */
export async function middleware(req: NextRequest) {
    const { pathname } = req.nextUrl;
    if (isOpen(pathname)) return NextResponse.next();

    const token = await getToken({ req, secret: process.env.NEXTAUTH_SECRET });
    if (token) return NextResponse.next();

    if (pathname.startsWith('/api/')) {
        // 헤더로 **어느 층이 막았는지** 알린다. 시크릿 없이 라이브를 찔러도
        // 라우트 자신의 401과 구분돼야 기계 경로가 살아 있는지 확인할 수 있다.
        return NextResponse.json({ error: 'Unauthorized' }, {
            status: 401,
            headers: { 'X-Auth-Gate': 'middleware' },
        });
    }

    const url = new URL('/login', req.url);
    url.searchParams.set('callbackUrl', pathname);
    return NextResponse.redirect(url);
}

/**
 * 정적 자산만 뺀다. 나머지는 전부 위 판정을 지난다 — 매처가 통과 목록을
 * 겸하던 옛 구조에서는 매처에 없는 것이 곧 공개였다.
 */
export const config = {
    matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
