import { NextResponse } from 'next/server';

// [V8.9.9.5] 엑셀 다운로드 API Route
// GitHub raw URL은 private 레포에서 인증이 필요하므로, 서버사이드에서 받아서 전달
export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
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
