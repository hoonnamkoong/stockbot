import { NextResponse } from 'next/server';
import { placeRealOrder } from '@/lib/kis-api';
import { sendTelegramMessage } from '@/lib/telegram-service';
import fs from 'fs/promises';
import path from 'path';
import axios from 'axios';

const VIRTUAL_PORTFOLIO_PATH = path.join(process.cwd(), 'data', 'portfolio_virtual.json');
const PIN = process.env.TRADE_PIN || '1234';

export async function POST(request: Request) {
    try {
        const body = await request.json();
        const { code, qty, price, side, isVirtual, pin } = body;

        // Validation
        if (!code || !qty || !side) {
            return NextResponse.json({ error: '필수 파라미터 누락' }, { status: 400 });
        }

        // 1. PIN Verification (for Real trade)
        if (!isVirtual && pin !== PIN) {
            return NextResponse.json({ error: 'Invalid TRADING PIN' }, { status: 403 });
        }

        let result: any;

        if (isVirtual) {
            // [VIRTUAL] Direct JSON Update (SSOT)
            const data = await fs.readFile(VIRTUAL_PORTFOLIO_PATH, 'utf-8');
            const portfolio = JSON.parse(data);
            
            const tradePrice = Number(price) || 50000; 
            const totalCost = tradePrice * Number(qty);

            if (side === 'buy') {
                if (portfolio.cash < totalCost) throw new Error('가상 예수금이 부족합니다.');
                portfolio.cash -= totalCost;
                if (!portfolio.holdings[code]) {
                    portfolio.holdings[code] = { name: code, qty: 0, avg_price: 0, days_held: 0 };
                }
                const h = portfolio.holdings[code];
                const newTotalCost = (h.qty * h.avg_price) + totalCost;
                h.qty += Number(qty);
                h.avg_price = newTotalCost / h.qty;
            } else {
                if (!portfolio.holdings[code] || portfolio.holdings[code].qty < Number(qty)) {
                    throw new Error('가상 보유 수량이 부족합니다.');
                }
                portfolio.cash += totalCost;
                portfolio.holdings[code].qty -= Number(qty);
                if (portfolio.holdings[code].qty === 0) delete portfolio.holdings[code];
            }

            portfolio.trade_log.push({
                date: new Date().toISOString(),
                type: side.toUpperCase(),
                code,
                name: code,
                price: tradePrice,
                qty: Number(qty),
                reason: 'Manual Virtual Trade'
            });

            await fs.writeFile(VIRTUAL_PORTFOLIO_PATH, JSON.stringify(portfolio, null, 2));
            result = { status: 'SUCCESS', msg: '가상 주문이 로컬 데이터에 반영되었습니다.' };
        } else {
            // [REAL] Direct KIS REST API
            result = await placeRealOrder(code, Number(qty), Number(price), side);
        }

        return NextResponse.json({ success: true, data: result });
    } catch (error: any) {
        console.error('[API-Order] Error:', error.message);
        return NextResponse.json({ success: false, error: error.message }, { status: 500 });
    }
}
