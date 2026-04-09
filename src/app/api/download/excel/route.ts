import { NextResponse } from 'next/server';

// [V8.9.9.5] 엑셀 다운로드 API Route
// GitHub raw URL은 private 레포에서 인증이 필요하므로, 서버사이드에서 받아서 전달
export const dynamic = 'force-dynamic';

export async function GET() {
    const GITHUB_BASE = 'https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data';
    const FILENAME = 'trending_integrated.xlsx';

    try {
        const res = await fetch(`${GITHUB_BASE}/${FILENAME}?t=${Date.now()}`, {
            cache: 'no-store',
            headers: {
                'User-Agent': 'StockBot-Vercel/1.0',
            }
        });

        if (!res.ok) {
            // 파일이 없으면 안내 메시지 반환
            return NextResponse.json(
                { error: 'Excel file not yet available. Please wait for the next scheduled data update (runs every hour on weekdays 9AM-4PM KST).' },
                { status: 404 }
            );
        }

        const buffer = await res.arrayBuffer();

        return new NextResponse(buffer, {
            status: 200,
            headers: {
                'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'Content-Disposition': `attachment; filename="stockbot_research_${new Date().toISOString().slice(0, 10)}.xlsx"`,
                'Cache-Control': 'no-store',
            },
        });
    } catch (error: any) {
        return NextResponse.json({ error: error.message }, { status: 500 });
    }
}
