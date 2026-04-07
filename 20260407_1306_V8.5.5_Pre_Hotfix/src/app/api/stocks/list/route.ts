import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

export async function GET() {
    try {
        const fs = require('fs/promises');
        const path = require('path');

        // Vercel 환경에서는 로컬 파일을 쓸 수 없으므로, public 디렉토리를 런타임에 읽음
        // 로컬 개발 환경에서는 public/stock_master.json 사용
        const filePath = path.join(process.cwd(), 'public', 'stock_master.json');

        const fileContent = await fs.readFile(filePath, 'utf-8');
        const parsed = JSON.parse(fileContent);

        // 배열 형식 보장: [{code, name}, ...] 형식이어야 함
        let stocks: Array<{code: string, name: string}> = [];
        if (Array.isArray(parsed)) {
            // 직접 배열인 경우 (update_stock_master.py 결과물)
            stocks = parsed.filter(s => s.code && s.name);
        } else if (parsed.stocks && Array.isArray(parsed.stocks)) {
            // {stocks: [...]} 래핑 형식
            stocks = parsed.stocks.filter((s: any) => s.code && s.name);
        }

        if (stocks.length === 0) {
            throw new Error('종목 데이터가 비어있습니다');
        }

        return NextResponse.json({ stocks });

    } catch (error) {
        console.error('[StockList] Failed to load stock_master.json:', error);
        // 최소 폴백 목록 (서버 구동 보장용)
        const stocks = [
            { code: '005930', name: '삼성전자' },
            { code: '000660', name: 'SK하이닉스' },
            { code: '035420', name: 'NAVER' },
            { code: '035720', name: '카카오' },
            { code: '005380', name: '현대차' },
            { code: '051910', name: 'LG화학' },
            { code: '006400', name: '삼성SDI' },
            { code: '003550', name: 'LG' },
        ];
        return NextResponse.json({ stocks });
    }
}
