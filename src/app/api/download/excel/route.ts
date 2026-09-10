import { NextResponse } from 'next/server';
import { getToken } from 'next-auth/jwt';

// [V8.9.9.5] 엑셀 다운로드 API Route
// GitHub raw URL은 private 레포에서 인증이 필요하므로, 서버사이드에서 받아서 전달
export const dynamic = 'force-dynamic';

// `/research`가 2026-09-10에 비공개로 돌아왔다. 이 파일을 부르는 곳은 그 페이지의
// 사이드바 하나뿐이므로 여기도 세션 뒤에 있어야 의도가 맞는다.
//
// **보안이 아니라 의도 정합성이다.** 원본은 db-data(공개 브랜치)라 막아도 데이터가
// 숨겨지지는 않는다([[security-posture-public-repo]]). 다만 '공개면은 / 한 장'이라는
// 규칙에 이 엔드포인트가 예외로 남아 있을 이유가 없다.
export async function GET(request: Request) {
    const token = await getToken({ req: request as any, secret: process.env.NEXTAUTH_SECRET });
    if (!token) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

    const { searchParams } = new URL(request.url);
    const month = searchParams.get('month'); // YYYY-MM 형식

    const GITHUB_BASE = 'https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data';
    const FILENAME = month ? `trending_integrated_${month}.xlsx` : 'trending_integrated.xlsx';

    try {
        const res = await fetch(`${GITHUB_BASE}/${FILENAME}?t=${Date.now()}`, {
            cache: 'no-store',
            headers: {
                'User-Agent': 'StockBot-Vercel/1.0',
            }
        });

        if (!res.ok) {
            return NextResponse.json(
                { error: `Excel file (${FILENAME}) not yet available.` },
                { status: 404 }
            );
        }

        const buffer = await res.arrayBuffer();
        const displayFilename = month ? `stockbot_monthly_${month}.xlsx` : `stockbot_latest_${new Date().toISOString().slice(0, 10)}.xlsx`;

        return new NextResponse(buffer, {
            status: 200,
            headers: {
                'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'Content-Disposition': `attachment; filename="${displayFilename}"`,
                'Cache-Control': 'no-store',
            },
        });
    } catch (error: any) {
        return NextResponse.json({ error: error.message }, { status: 500 });
    }
}
