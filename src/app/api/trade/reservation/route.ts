import { NextResponse } from 'next/server';
import fs from 'fs/promises';
import path from 'path';

export const dynamic = 'force-dynamic';
const RESERVATIONS_PATH = path.join(process.cwd(), 'data', 'reservations.json');

export async function GET() {
    try {
        let reservations: any[] = [];
        try {
            const data = await fs.readFile(RESERVATIONS_PATH, 'utf-8');
            reservations = JSON.parse(data);
        } catch (e) {}
        return NextResponse.json({ success: true, data: reservations });
    } catch (error: any) {
        return NextResponse.json({ success: false, error: error.message }, { status: 500 });
    }
}

export async function POST(request: Request) {
    try {
        const body = await request.json();
        const { code, qty, price, side, time } = body;

        let reservations: any[] = [];
        try {
            const data = await fs.readFile(RESERVATIONS_PATH, 'utf-8');
            reservations = JSON.parse(data);
        } catch (e) {}

        const newRes = {
            id: `res_${Date.now()}`,
            code,
            qty,
            price,
            side,
            time: time || '15:15',
            status: 'PENDING',
            created_at: new Date().toISOString()
        };

        reservations.push(newRes);
        await fs.mkdir(path.dirname(RESERVATIONS_PATH), { recursive: true });
        await fs.writeFile(RESERVATIONS_PATH, JSON.stringify(reservations, null, 2));

        return NextResponse.json({ success: true, data: newRes });
    } catch (error: any) {
        return NextResponse.json({ success: false, error: error.message }, { status: 500 });
    }
}
