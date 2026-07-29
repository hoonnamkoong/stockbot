import { NextRequest, NextResponse } from 'next/server';
import { getRealTradeHistory } from '@/lib/kis-api';
import { SIM_REGISTRY } from '@/lib/sim-registry.generated';
import { createBucketCache, dbDataUrl } from '@/lib/db-data';

/**
 * [V50.2] Trading History API (Refactored)
 * - 실거래(real): KIS API 직접 조회
 * - 시뮬레이터: GitHub db-data 브랜치 CSV 파싱
 */

export const dynamic = 'force-dynamic';

/**
 * KIS API를 통해 실제 체결 내역을 가져옵니다.
 */
async function fetchRealHistory() {
    try {
        return await getRealTradeHistory();
    } catch (e: any) {
        console.error('[HistoryAPI] KIS 실거래 조회 실패:', e.message);
        return [];
    }
}

/**
 * GitHub에서 특정 시뮬레이터의 CSV 파일을 가져와 파싱합니다.
 */
async function fetchSimHistory(fileInfo: { type: string, name: string }) {
    try {
        const res = await fetch(dbDataUrl(fileInfo.name), { cache: 'no-store' });
        if (!res.ok) return [];

        const content = await res.text();
        const lines = content.split('\n').filter(line => line.trim().length > 0);
        if (lines.length <= 1) return [];

        const parseCSVLine = (text: string) =>
            text.split(',').map(v => v.trim().replace(/^"|"$/g, ''));

        const headers = parseCSVLine(lines[0]);
        const entries: any[] = [];
        
        for (let i = 1; i < lines.length; i++) {
            const values = parseCSVLine(lines[i]);
            if (values.length < 2) continue;

            const entry: any = { type: fileInfo.type };
            headers.forEach((h, idx) => {
                const v = values[idx] || '';
                if (h === 'timestamp') entry.time = v;
                else if (h === 'symbol') entry.symbol = v;
                else if (h === 'action') entry.action = v.toUpperCase();
                else if (h === 'price') entry.price = v;
                else if (h === 'quantity') entry.qty = v;
                else if (h === 'total_amount') entry.amount = v;
                else if (h === 'roi') entry.roi = v;
                else if (h === 'reason') entry.reason = v;
            });
            
            // 금액 보정 (필요시)
            if (!entry.amount && entry.price && entry.qty) {
                const p = parseInt((entry.price || '').replace(/,/g, ''));
                const q = parseInt(entry.qty);
                if (!isNaN(p) && !isNaN(q)) {
                    entry.amount = (p * q).toLocaleString();
                }
            }
            entries.push(entry);
        }
        return entries;
    } catch (err) {
        console.error(`[HistoryAPI] Error fetching ${fileInfo.name}:`, err);
        return [];
    }
}

/**
 * 심 매매 기록(GitHub CSV 12개)만 신선도 버킷 단위로 재사용한다.
 *
 * **실거래(KIS)는 캐시하지 않는다.** 자기 체결이 화면에 늦게 뜨는 것은 다른 종류의
 * 문제라 30초라도 미룰 이유가 없다. 심 CSV는 10분마다 도는 파이프라인이 쓴다.
 */
const loadSimHistories = createBucketCache(async () => {
    // type은 매니페스트 id다 — 대시보드 카드가 이 값으로 자기 기록을 골라낸다.
    // 손으로 적던 시절 심8·심9·심9-1이 빠져 있어 그 셋의 기록 표가 늘 비어 있었다.
    // 은퇴한 심(sim_original·conservative·aggressive)도 여기서 함께 사라진다 —
    // 매니페스트에 없고 화면 어디도 그 type을 참조하지 않는 죽은 fetch였다.
    const simFiles = SIM_REGISTRY.map((s) => ({ type: s.id, name: s.csvFile }));
    const histories = await Promise.all(simFiles.map(file => fetchSimHistory(file)));
    return histories.flat();
});

export async function GET(req: NextRequest) {
    try {
        const [realHistory, simHistory] = await Promise.all([
            fetchRealHistory(),
            loadSimHistories(),
        ]);

        const allHistory = [...realHistory, ...simHistory];

        // 시간순 정렬 (최신 → 과거)
        allHistory.sort((a, b) => {
            const timeA = new Date(a.time).getTime();
            const timeB = new Date(b.time).getTime();
            return isNaN(timeB) || isNaN(timeA) ? 0 : timeB - timeA;
        });

        return NextResponse.json({ 
            success: true, 
            count: allHistory.length,
            data: allHistory 
        });

    } catch (error: any) {
        console.error("[API History Error]", error);
        return NextResponse.json({ 
            success: false, 
            error: "Failed to fetch trade history",
            details: error.message 
        }, { status: 500 });
    }
}
