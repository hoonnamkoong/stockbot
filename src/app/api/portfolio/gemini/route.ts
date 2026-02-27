import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

export async function GET() {
    try {
        const filePath = path.join(process.cwd(), 'data', 'gemini_portfolio.json');

        if (!fs.existsSync(filePath)) {
            return NextResponse.json({
                cash: 3000000,
                holdings: {},
                trade_log: [],
                last_update: ''
            });
        }

        const fileContent = fs.readFileSync(filePath, 'utf-8');
        const data = JSON.parse(fileContent);
        return NextResponse.json(data);
    } catch (error) {
        console.error('Error reading gemini portfolio data:', error);
        return NextResponse.json({ error: 'Failed to read gemini portfolio data' }, { status: 500 });
    }
}
