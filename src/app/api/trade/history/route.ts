import { NextRequest, NextResponse } from 'next/server';
import { getRealTradeHistory } from '@/lib/kis-api';
import { SIM_REGISTRY } from '@/lib/sim-registry.generated';

/**
 * [V50.2] Trading History API (Refactored)
 * - 실거래(real): KIS API 직접 조회
 * - 시뮬레이터: GitHub db-data 브랜치 CSV 파싱
 */

export const dynamic = 'force-dynamic';

const GITHUB_BASE = 'https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data';

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
        const cacheBuster = Date.now();
        const res = await fetch(`${GITHUB_BASE}/${fileInfo.name}?t=${cacheBuster}`, { cache: 'no-store' });
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

export async function GET(req: NextRequest) {
    try {
        // type은 매니페스트 id다 — 대시보드 카드가 이 값으로 자기 기록을 골라낸다.
        // 손으로 적던 시절 심8·심9·심9-1이 빠져 있어 그 셋의 기록 표가 늘 비어 있었다.
        // 은퇴한 심(sim_original·conservative·aggressive)도 여기서 함께 사라진다 —
        // 매니페스트에 없고 화면 어디도 그 type을 참조하지 않는 죽은 fetch였다.
        const simFiles = SIM_REGISTRY.map((s) => ({ type: s.id, name: s.csvFile }));

        // 병렬 요청 수행
        const [realHistory, ...simHistories] = await Promise.all([
            fetchRealHistory(),
            ...simFiles.map(file => fetchSimHistory(file))
        ]);

        const allHistory = [...realHistory, ...simHistories.flat()];

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
