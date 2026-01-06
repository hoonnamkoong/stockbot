import { NextResponse } from 'next/server';
import { placeOrder } from '@/lib/kis';
import path from 'path';
import fs from 'fs/promises';

async function updateOrderHistory(code: string) {
    try {
        const filePath = path.join(process.cwd(), 'data', 'order_history.json');

        let history: Record<string, string> = {};
        try {
            const data = await fs.readFile(filePath, 'utf-8');
            history = JSON.parse(data);
        } catch { }

        const now = new Date();
        const dateStr = now.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false });

        history[code] = dateStr;
        await fs.writeFile(filePath, JSON.stringify(history, null, 2), 'utf-8');
    } catch (e: any) {
        // On Vercel (Read-Only), this will fail. We should NOT fail the order because of this.
        console.warn("Failed to update order history (likely Read-Only FS):", e.message);
    }
}

export async function POST(request: Request) {
    try {
        const body = await request.json();
        const { code, qty, price, side, pin } = body;

        // PIN Verification
        if (pin !== process.env.TRADE_PIN) {
            return NextResponse.json({ error: 'Invalid PIN' }, { status: 401 });
        }

        if (!code || !qty || !side) {
            return NextResponse.json({ error: 'Missing parameters' }, { status: 400 });
        }

        const output = await placeOrder(code, Number(qty), Number(price), side);

        // Track history if BUY
        if (side === 'buy') {
            await updateOrderHistory(code);
        }

        return NextResponse.json({ success: true, data: output });

    } catch (error: any) {
        return NextResponse.json({ error: error.message }, { status: 500 });
    }
}
