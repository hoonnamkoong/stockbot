import { NextResponse } from 'next/server';
import { createBucketCache, dbDataUrl } from '@/lib/db-data';

export const dynamic = 'force-dynamic';

/**
 * 리서치 표의 데이터. **공개 페이지(`/`)가 쓰는 유일한 수집 데이터원이다.**
 *
 * 한 번 계산에 GitHub raw 5회. 생산자는 10분마다 도는 파이프라인이라, 같은 신선도
 * 버킷 안에서는 한 번만 가져온다(`src/lib/db-data.ts`) — `simulation/stats`·
 * `trade/history`가 이미 쓰는 방식이다.
 *
 * 2026-09-10까지 이 라우트만 캐시가 없었고, 게다가 요청마다 달라지는 쿼리를 붙여
 * GitHub의 캐시까지 무력화하고 있었다. 요청 하나가 오리진 5회였다는 뜻이다.
 * (그 버스터를 금지하는 게이트는 `tests/test_dashboard_freshness.py`에 이미
 * 있었는데, 이 라우트가 헬퍼를 안 써서 검사 대상 밖이었다.) `/research`가
 * 로그인 뒤에 있을 때는 트래픽이 사람 한 명이라 안 드러났는데, 공개 페이지가
 * 이걸 쓰기 시작하면 봇 트래픽이 그대로 비용이 된다.
 *
 * **레이트리밋 대신 캐시인 이유:** 걱정거리가 남용이 아니라 **비용**이고, 이 데이터는
 * 누구에게나 같은 값이다. 사용자를 세는 것보다 오리진을 덜 치는 쪽이 맞다.
 */
const loadResearch = createBucketCache(async () => {
    const fetchRemote = async (filename: string, fallback: string) => {
        try {
            const res = await fetch(dbDataUrl(filename), { cache: 'no-store' });
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
        fetchRemote('reports.json', '[]'),
    ]);

    return {
        success: true,
        stocks: JSON.parse(stocksRaw),
        status: JSON.parse(statusRaw),
        analysis_5days: JSON.parse(a5Raw),
        analysis_3days: JSON.parse(a3Raw),
        reports: JSON.parse(reportsRaw),
    };
});

export async function GET() {
    try {
        return NextResponse.json(await loadResearch());
    } catch (error: any) {
        console.error('[ResearchAPI] Error:', error);
        return NextResponse.json({ success: false, error: error.message }, { status: 500 });
    }
}
