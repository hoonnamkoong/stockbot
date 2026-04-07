import { NextResponse } from 'next/server';
import fs from 'fs/promises';
import path from 'path';

export const dynamic = 'force-dynamic';

export async function GET() {
    try {
        const dataDir = path.join(process.cwd(), 'data');
        
        // [V8.6.2 Hotfix] 필수 데이터 파일 로드
        const latestStocksPath = path.join(dataDir, 'latest_stocks.json');
        const statusPath = path.join(dataDir, 'status.json');
        const analysis5DaysPath = path.join(dataDir, 'analysis_5days.json');
        const analysis3DaysPath = path.join(dataDir, 'analysis_3days.json');
        const reportsPath = path.join(dataDir, 'reports.json');

        const [stocksRaw, statusRaw, a5Raw, a3Raw, reportsRaw] = await Promise.all([
            fs.readFile(latestStocksPath, 'utf-8').catch(() => '[]'),
            fs.readFile(statusPath, 'utf-8').catch(() => '{"last_updated": "unknown"}'),
            fs.readFile(analysis5DaysPath, 'utf-8').catch(() => '[]'),
            fs.readFile(analysis3DaysPath, 'utf-8').catch(() => '[]'),
            fs.readFile(reportsPath, 'utf-8').catch(() => '[]')
        ]);

        // [V8.6.2 Hotfix] JSON 파싱 에러(NaN, Infinity) 방지를 위한 정규식 치환
        const sanitize = (raw: string) => raw.replace(/\bNaN\b/g, 'null').replace(/\bInfinity\b/g, 'null');

        return NextResponse.json({
            success: true,
            stocks: JSON.parse(sanitize(stocksRaw)),
            status: JSON.parse(sanitize(statusRaw)),
            analysis_5days: JSON.parse(sanitize(a5Raw)),
            analysis_3days: JSON.parse(sanitize(a3Raw)),
            reports: JSON.parse(sanitize(reportsRaw))
        });

    } catch (error: any) {
        console.error('[ResearchAPI] Error:', error);
        return NextResponse.json({ success: false, error: error.message }, { status: 500 });
    }
}
