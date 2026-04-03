import { NextResponse } from 'next/server';
import fs from 'fs/promises';
import path from 'path';

export const dynamic = 'force-dynamic';

const STATUS_PATH = path.join(process.cwd(), 'data', 'order_status.json');

export async function GET() {
    try {
        let statuses = {};
        try {
            const data = await fs.readFile(STATUS_PATH, 'utf-8');
            statuses = JSON.parse(data);
        } catch (e) {
            // File might not exist yet
        }
        
        return NextResponse.json({ success: true, data: statuses });
    } catch (error: any) {
        console.error('[OrderStatus API] Exception:', error.message);
        return NextResponse.json({ success: false, error: error.message }, { status: 500 });
    }
}
