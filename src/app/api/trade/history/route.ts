import { NextRequest, NextResponse } from 'next/server';
import { getRealTradeHistory } from '@/lib/kis-api';

/**
 * [V50.1] Trading History API
 * - 실거래(real): KIS inquire-daily-ccld API 직접 조회 (체결가/종목명 정확)
 * - 시뮬레이터: GitHub db-data 브랜치 CSV 파싱 (기존 방식 유지)
 */

export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
    try {
        const GITHUB_BASE = 'https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data';
        
        // 시뮬레이터 CSV 파일 목록
        const simFiles = [
            { type: 'sim_original',     name: 'trade_history_sim_original.csv' },
            { type: 'sim_conservative', name: 'trade_history_sim_conservative.csv' },
            { type: 'sim_aggressive',   name: 'trade_history_sim_aggressive.csv' },
            { type: 'sim_conviction',   name: 'trade_history_sim_conviction.csv' }
        ];

        let allHistory: any[] = [];

        // 1. 실거래 내역: KIS API 직접 조회
        // - CSV 파싱 방식의 구조적 한계(주문접수 응답에 체결가 없음)를 해결
        // - KIS inquire-daily-ccld API는 실제 체결가, 종목명, 수량을 모두 반환
        try {
            const realHistory = await getRealTradeHistory();
            allHistory.push(...realHistory);
            console.log(`[HistoryAPI] KIS 실거래 체결 내역 ${realHistory.length}건 로드`);
        } catch (e: any) {
            console.error('[HistoryAPI] KIS 실거래 조회 실패, 건너뜀:', e.message);
        }

        // 2. 시뮬레이터 CSV 파싱 (기존 로직 유지)
        await Promise.all(simFiles.map(async (fileInfo) => {
            try {
                const cacheBuster = Date.now();
                const res = await fetch(`${GITHUB_BASE}/${fileInfo.name}?t=${cacheBuster}`, { cache: 'no-store' });
                if (!res.ok) return;

                const content = await res.text();
                const lines = content.split('\n').filter(line => line.trim().length > 0);
                
                if (lines.length > 1) {
                    // 쉼표 분리 (따옴표 미포함 CSV 기준)
                    const parseCSVLine = (text: string) =>
                        text.split(',').map(v => v.trim().replace(/^"|"$/g, ''));

                    const headers = parseCSVLine(lines[0]);
                    
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
                        
                        if (!entry.amount && entry.price && entry.qty) {
                            const p = parseInt((entry.price || '').replace(/,/g, ''));
                            const q = parseInt(entry.qty);
                            if (!isNaN(p) && !isNaN(q)) {
                                entry.amount = (p * q).toLocaleString();
                            }
                        }
                        allHistory.push(entry);
                    }
                }
            } catch (err) {
                console.error(`[HistoryAPI] Error fetching ${fileInfo.name}:`, err);
            }
        }));

        // 3. 시간순 정렬 (최신 → 과거)
        allHistory.sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime());

        return NextResponse.json({ 
            success: true, 
            count: allHistory.length,
            data: allHistory 
        });

    } catch (error: any) {
        console.error("[API History Error]", error);
        return NextResponse.json({ success: false, error: error.message }, { status: 500 });
    }
}
