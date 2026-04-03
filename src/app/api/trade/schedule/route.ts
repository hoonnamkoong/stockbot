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
            const all = JSON.parse(data);
            // Filter only PENDING for scheduling if needed, or return all
            reservations = all;
        } catch (e) {}

        return NextResponse.json({
            success: true,
            data: reservations || []
        });
    } catch (error: any) {
        return NextResponse.json({
            success: false,
            error: error.message
        }, { status: 500 });
    }
}
