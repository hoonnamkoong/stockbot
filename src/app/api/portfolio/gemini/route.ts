import { NextResponse } from 'next/server';
import path from 'path';
import fs from 'fs/promises';

export const dynamic = 'force-dynamic';

export async function GET() {
    try {
        const filePath = path.join(process.cwd(), 'data', 'gemini_portfolio.json');

        let data: any;
        try {
            const content = await fs.readFile(filePath, 'utf-8');
            data = JSON.parse(content);
        } catch {
            // 파일 없으면 기본값 (300만 초기 상태)
            data = {
                cash: 3000000,
                holdings: {},
                trade_log: [],
                last_update: new Date().toISOString()
            };
        }

        // cash 필드 기본값 보장
        if (typeof data.cash !== 'number') data.cash = 3000000;
        if (!data.holdings) data.holdings = {};
        if (!data.trade_log) data.trade_log = [];

        return NextResponse.json(data);
    } catch (error) {
        console.error('[GeminiPortfolio] Error reading local file:', error);
        return NextResponse.json({
            cash: 3000000,
            holdings: {},
            trade_log: [],
            last_update: ''
        });
    }
}
