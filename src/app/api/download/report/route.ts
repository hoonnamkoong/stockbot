import { NextRequest, NextResponse } from 'next/server';
import { getToken } from 'next-auth/jwt';

/**
 * [V50.1] 리서치 리포트 다운로드 API
 * reports.json의 filename을 받아 GitHub db-data 브랜치에서 xlsx 파일을 서빙합니다.
 * filename 형식: monthly_research_2026-04.xlsx (reports/reports 폴더 기준)
 */
export const dynamic = 'force-dynamic';

// `/research`가 2026-09-10에 비공개로 돌아왔다. 이 파일을 부르는 곳은 그 페이지의
// 사이드바 하나뿐이므로 여기도 세션 뒤에 있어야 의도가 맞는다.
//
// **보안이 아니라 의도 정합성이다.** 원본은 db-data(공개 브랜치)라 막아도 데이터가
// 숨겨지지는 않는다([[security-posture-public-repo]]). 다만 '공개면은 / 한 장'이라는
// 규칙에 이 엔드포인트가 예외로 남아 있을 이유가 없다.
export async function GET(request: NextRequest) {
    const token = await getToken({ req: request as any, secret: process.env.NEXTAUTH_SECRET });
    if (!token) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

    const { searchParams } = new URL(request.url);
    const filename = searchParams.get('filename');

    if (!filename) {
        return NextResponse.json({ error: 'filename 파라미터가 필요합니다.' }, { status: 400 });
    }

    const GITHUB_BASE = 'https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data';

    // filename이 경로 포함 여부에 따라 분기
    // 예: "monthly_research_2026-04.xlsx" → reports/ 하위
    // 예: "reports/monthly_research_2026-04.xlsx" → 그대로 사용
    const filePath = filename.startsWith('reports/')
        ? filename
        : `reports/${filename}`;

    const url = `${GITHUB_BASE}/${filePath}?t=${Date.now()}`;

    try {
        const res = await fetch(url, { cache: 'no-store' });

        if (!res.ok) {
            // 폴백: 루트 data/ 에서 시도 (구버전 호환)
            const fallbackUrl = `${GITHUB_BASE}/${filename}?t=${Date.now()}`;
            const fallback = await fetch(fallbackUrl, { cache: 'no-store' });
            if (!fallback.ok) {
                return NextResponse.json(
                    { error: `파일을 찾을 수 없습니다: ${filename}` },
                    { status: 404 }
                );
            }
            const buffer = await fallback.arrayBuffer();
            return new NextResponse(buffer, {
                status: 200,
                headers: {
                    'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    'Content-Disposition': `attachment; filename="${filename}"`,
                    'Cache-Control': 'no-store',
                },
            });
        }

        const buffer = await res.arrayBuffer();
        return new NextResponse(buffer, {
            status: 200,
            headers: {
                'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'Content-Disposition': `attachment; filename="${filename}"`,
                'Cache-Control': 'no-store',
            },
        });
    } catch (error: any) {
        return NextResponse.json({ error: error.message }, { status: 500 });
    }
}
