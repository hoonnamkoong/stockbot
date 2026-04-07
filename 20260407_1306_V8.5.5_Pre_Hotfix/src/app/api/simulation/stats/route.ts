import { NextResponse } from 'next/server';
import { exec } from 'child_process';
import path from 'path';
import { promisify } from 'util';

const execAsync = promisify(exec);

export async function GET() {
  try {
    // 1. 파이썬 스크립트 경로 설정
    const scriptPath = path.join(process.cwd(), 'src', 'strategy', 'simulators', 'get_all_stats.py');
    
    // 2. 파이썬 실행 및 결과 수신
    const { stdout, stderr } = await execAsync(`python "${scriptPath}"`);
    
    if (stderr) {
      console.error('[Simulation API] Python Stderr:', stderr);
    }
    
    // 3. JSON 파싱 및 반환
    const stats = JSON.parse(stdout);
    return NextResponse.json(stats);
    
  } catch (error) {
    console.error('[Simulation API] Error fetching stats:', error);
    return NextResponse.json(
      { error: 'Failed to fetch simulation stats' },
      { status: 500 }
    );
  }
}
