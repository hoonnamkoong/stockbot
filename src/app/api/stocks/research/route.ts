import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

export async function GET() {
    try {
        const GITHUB_BASE = 'https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data';
        
        // [V8.9.9] GitHub Raw DB에서 원격 데이터 로드 (Vercel 배포 대응)
        const fetchRemote = async (filename: string, fallback: string) => {
            try {
                // [V8.9.9.5] GitHub Raw 캐시 무력화를 위한 타임스탬프 쿼리 추가
                const res = await fetch(`${GITHUB_BASE}/${filename}?t=${Date.now()}`, { 
                    cache: 'no-store',
                    next: { revalidate: 0 }
                });
                if (!res.ok) throw new Error(`Fetch failed: ${res.statusText}`);
                return await res.text();
            } catch (err) {
                console.error(`[ResearchAPI] Failed to fetch ${filename}:`, err);
                return fallback;
            }
        };

        const [stocksRaw, statusRaw, a5Raw, a3Raw, reportsRaw] = await Promise.all([
            fetchRemote('latest_stocks.json', '[]'),
            fetchRemote('status.json', '{"last_updated": "unknown"}'),
            fetchRemote('analysis_5days.json', '[]'),
            fetchRemote('analysis_3days.json', '[]'),
            fetchRemote('reports.json', '[]')
        ]);

        return NextResponse.json({
            success: true,
            stocks: JSON.parse(stocksRaw),
            status: JSON.parse(statusRaw),
            analysis_5days: JSON.parse(a5Raw),
            analysis_3days: JSON.parse(a3Raw),
            reports: JSON.parse(reportsRaw)
        });

    } catch (error: any) {
        console.error('[ResearchAPI] Error:', error);
        return NextResponse.json({ success: false, error: error.message }, { status: 500 });
    }
}
