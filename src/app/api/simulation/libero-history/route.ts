import { NextResponse } from 'next/server';
import { readFile } from 'fs/promises';
import path from 'path';
import { ANALYZERS } from '@/lib/sim-registry.generated';
import { createBucketCache, dbDataUrl } from '@/lib/db-data';

export const dynamic = 'force-dynamic';

/**
 * Sim7 리베로 2주 히스토리 API
 * - libero_log: GitHub에서 daily_regime_log 조회
 * - market_data: kospi_top100_close.csv에서 실제 시장 breadth 계산
 *
 * **신선도 버킷 캐시를 쓴다.** 2026-09-10 감사 전까지 이 라우트만 캐시가 없었고
 * 요청마다 달라지는 쿼리로 CDN까지 무력화해, 무인증 호출 하나가 오리진 2회 +
 * 응답 125KB였다. 공개면은 아니지만 인증도 없어 봇 트래픽이 그대로 비용이 된다.
 *
 * 같은 함정을 `stocks/research`에서 먼저 고쳤는데 이 라우트가 남아 있었다.
 * `tests/test_dashboard_freshness.py`의 캐시버스터 금지 규칙이 "db-data 헬퍼를
 * import 하는 파일"만 검사하는데, 헬퍼를 안 쓰면 **검사 대상 밖**이기 때문이다 —
 * 이제 헬퍼를 쓰므로 그 게이트가 이 파일도 지킨다.
 */
const loadLiberoHistory = createBucketCache(async () => {
    // 1) 리베로 daily_regime_log + calibration_log + 당일 나우캐스트(intraday)
    let liberoLog: any[] = [];
    let calibrationLog: any[] = [];
    let intraday: any = null;
    let intradayScoreLog: any[] = [];
    try {
        // 국면 상태 파일명은 매니페스트의 분석기 심에서 온다(여기 적지 않는다).
        const res = await fetch(dbDataUrl(ANALYZERS[0].stateFile), { cache: 'no-store' });
        if (res.ok) {
            const s = await res.json();
            liberoLog = s.daily_regime_log ?? [];
            calibrationLog = s.calibration_log ?? [];
            intraday = s.intraday ?? null;
            intradayScoreLog = s.intraday_score_log ?? [];
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
    const csvPath = path.join(process.cwd(), 'output', 'kospi_top100_close.csv');
    const marketData: { date: string; breadth: number; regime: string }[] = [];
    try {
        let raw: string;
        try {
            const csvRes = await fetch(dbDataUrl('kospi_top100_close.csv'), { cache: 'no-store' });
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

    return {
        libero_log: liberoLog,
        market_data: marketData,
        calibration_log: calibrationLog,
        intraday,
        intraday_score_log: intradayScoreLog,
    };
});

export async function GET() {
    try {
        return NextResponse.json(await loadLiberoHistory());
    } catch (error: any) {
        return NextResponse.json({ error: error.message }, { status: 500 });
    }
}
