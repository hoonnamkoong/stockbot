import { NextResponse } from 'next/server';
import path from 'path';
import fs from 'fs/promises';

export const dynamic = 'force-dynamic';

export async function POST() {
    try {
        // 매월 1일 자동 갱신용 트리거 엔드포인트
        // update_stock_master.py를 실행하여 KRX 전체 종목을 갱신함
        const { execFile } = require('child_process');
        const { promisify } = require('util');
        const execFileAsync = promisify(execFile);

        const scriptPath = path.join(process.cwd(), 'update_stock_master.py');
        const outputPath = path.join(process.cwd(), 'public', 'stock_master.json');

        // 스크립트 존재 확인
        try {
            await fs.access(scriptPath);
        } catch {
            return NextResponse.json({ error: 'update_stock_master.py not found' }, { status: 500 });
        }

        await execFileAsync('python', [scriptPath], { cwd: process.cwd(), timeout: 60000 });

        // 갱신 결과 확인
        const content = await fs.readFile(outputPath, 'utf-8');
        const stocks = JSON.parse(content);
        const count = Array.isArray(stocks) ? stocks.length : 0;

        return NextResponse.json({
            success: true,
            message: `종목 마스터 갱신 완료 (${count}개)`,
            updated_at: new Date().toISOString(),
            count
        });

    } catch (error: any) {
        console.error('[StockRefresh] Error:', error.message);
        return NextResponse.json({ error: error.message }, { status: 500 });
    }
}

export async function GET() {
    // 현재 파일 상태 반환 (조회용)
    try {
        const outputPath = path.join(process.cwd(), 'public', 'stock_master.json');
        const stat = await fs.stat(outputPath);
        const content = await fs.readFile(outputPath, 'utf-8');
        const stocks = JSON.parse(content);
        return NextResponse.json({
            count: Array.isArray(stocks) ? stocks.length : 0,
            last_modified: stat.mtime.toISOString()
        });
    } catch {
        return NextResponse.json({ count: 0, last_modified: null });
    }
}
