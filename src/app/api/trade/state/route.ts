import { NextResponse } from 'next/server';
import fs from 'fs/promises';
import path from 'path';

/**
 * [V8.9.9] 시뮬레이터 상태 동기화 API
 * data/ 디렉토리의 시뮬레이터 상태 파일(JSON)을 읽어 반환합니다.
 */
export async function GET(request: Request) {
    const { searchParams } = new URL(request.url);
    const type = searchParams.get('type') || 'original'; // original, aggressive, conviction
    
    const dataDir = path.join(process.cwd(), 'data');
    const stateFile = `sim_${type}_state.json`;
    const filePath = path.join(dataDir, stateFile);

    try {
        const rawData = await fs.readFile(filePath, 'utf-8');
        return NextResponse.json({
            success: true,
            type: type,
            state: JSON.parse(rawData)
        });
    } catch (error: any) {
        console.error(`[API] Failed to read simulator state (${type}):`, error.message);
        
        // 파일이 없을 경우 기본 초기값 반환 (V8.6.2 규격 300만 원)
        return NextResponse.json({
            success: false,
            message: "State file not found, returning default",
            state: {
                cash: 3000000,
                portfolio: {},
                history: [],
                initial_cash: 3000000
            }
        });
    }
}
