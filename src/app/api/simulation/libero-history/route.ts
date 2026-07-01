import { NextResponse } from 'next/server';
import { readFile } from 'fs/promises';
import path from 'path';

export const dynamic = 'force-dynamic';

/**
 * Sim7 리베로 2주 히스토리 API
 * - libero_log: GitHub에서 daily_regime_log 조회
 * - market_data: 로컬 kospi_top100_close.csv에서 실제 시장 breadth 계산
 */
export async function GET() {
    try {
        const GITHUB_BASE = 'https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data';

        // 1) 리베로 daily_regime_log + calibration_log + 예측기 채택/누적 채점
        let liberoLog: any[] = [];
        let calibrationLog: any[] = [];
        let preferredPredictor: string | null = null;
        let scoreTotals: any = null;
        try {
            const res = await fetch(`${GITHUB_BASE}/sim_libero_state.json?t=${Date.now()}`, { cache: 'no-store' });
            if (res.ok) {
                const s = await res.json();
                liberoLog = s.daily_regime_log ?? [];
                calibrationLog = s.calibration_log ?? [];
                preferredPredictor = s.preferred_predictor ?? null;
                scoreTotals = s.score_totals ?? null;
                // daily_regime_log 없으면 regime_history + last_run으로 근사 구성
                if (liberoLog.length === 0 && s.regime_history?.length > 0 && s.last_run) {
                    const lastDate = new Date(s.last_run.replace(' ', 'T'));
                    liberoLog = s.regime_history.map((regime: string, i: number) => {
                        const d = new Date(lastDate);
                        d.setDate(d.getDate() - (s.regime_history.length - 1 - i));
                        return {
                            date: d.toISOString().slice(0, 10),
                            regime,
                            bull_score: regime === 'BULL' ? 70 : regime === 'BEAR' ? 30 : 50,
                            breadth: null,
                        };
                    });
                }
            }
        } catch { /* GitHub 조회 실패 시 빈 배열 */ }

        // 2) KOSPI top100 close CSV → 날짜별 breadth 계산
        // GitHub db-data 우선, 없으면 로컬 static 파일 사용
        const GITHUB_CSV = 'https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data/kospi_top100_close.csv';
        const csvPath = path.join(process.cwd(), 'output', 'kospi_top100_close.csv');
        const marketData: { date: string; breadth: number; regime: string }[] = [];
        try {
            let raw: string;
            try {
                const csvRes = await fetch(`${GITHUB_CSV}?t=${Date.now()}`, { cache: 'no-store' });
                if (csvRes.ok) {
                    raw = await csvRes.text();
                } else {
                    raw = await readFile(csvPath, 'utf-8');
                }
            } catch {
                raw = await readFile(csvPath, 'utf-8');
            }
            const lines = raw.split('\n').filter(l => l.trim());
            const headers = lines[0].split(',');
            const stockCount = headers.length - 1; // 첫 컬럼이 date

            // 날짜-가격 맵
            const rows: { date: string; prices: (number | null)[] }[] = [];
            for (let i = 1; i < lines.length; i++) {
                const cols = lines[i].split(',');
                const dateRaw = cols[0].replace(/^﻿/, '').trim();
                if (dateRaw.length !== 8) continue;
                const dateStr = `${dateRaw.slice(0, 4)}-${dateRaw.slice(4, 6)}-${dateRaw.slice(6, 8)}`;
                const prices = cols.slice(1).map(v => v.trim() ? parseFloat(v.trim()) : null);
                rows.push({ date: dateStr, prices });
            }

            // 최근 14 거래일 breadth 계산
            const last14 = rows.slice(-14);
            for (let i = 1; i < last14.length; i++) {
                const prev = last14[i - 1].prices;
                const curr = last14[i].prices;
                let ups = 0, total = 0;
                for (let j = 0; j < stockCount; j++) {
                    if (prev[j] != null && curr[j] != null && prev[j]! > 0) {
                        total++;
                        if (curr[j]! > prev[j]!) ups++;
                    }
                }
                const breadth = total > 0 ? Math.round((ups / total) * 100) : 50;
                const regime = breadth >= 60 ? 'BULL' : breadth <= 40 ? 'BEAR' : 'SIDEWAYS';
                marketData.push({ date: last14[i].date, breadth, regime });
            }
        } catch { /* CSV 없으면 빈 배열 */ }

        return NextResponse.json({
            libero_log: liberoLog, market_data: marketData, calibration_log: calibrationLog,
            preferred_predictor: preferredPredictor, score_totals: scoreTotals,
        });
    } catch (error: any) {
        return NextResponse.json({ error: error.message }, { status: 500 });
    }
}
