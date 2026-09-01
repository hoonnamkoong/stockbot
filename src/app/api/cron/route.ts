import { NextResponse } from 'next/server';
import axios from 'axios';
import { pickWorkflow } from '@/lib/cron-target';

export const dynamic = 'force-dynamic';
export const maxDuration = 60;

export async function GET(request: Request) {
    const GITHUB_PAT = process.env.GITHUB_PAT;
    const REPO_OWNER = 'hoonnamkoong';
    const REPO_NAME = 'stockbot';

    try {
        // Parse debug params
        const urlStr = request.url || '';
        const parsedUrl = urlStr.startsWith('http') ? new URL(urlStr) : new URL(urlStr, 'http://localhost');
        const { searchParams } = parsedUrl;
        const debugHour = searchParams.get('hour');
        const debugMinute = searchParams.get('minute');

        // Get current KST time
        const now = new Date();
        const kstTime = new Date(now.getTime() + 9 * 60 * 60 * 1000);

        // Use debug time if provided, otherwise use real time
        let hour = debugHour ? parseInt(debugHour) : kstTime.getHours();
        let minute = debugMinute ? parseInt(debugMinute) : kstTime.getMinutes();
        const dayOfWeek = kstTime.getDay(); // 0=Sun, 6=Sat

        // Allow debug to bypass current time for logs
        if (debugHour) {
            console.log(`[Debug] Simulating time: ${hour}:${minute} (Real: ${kstTime.getHours()}:${kstTime.getMinutes()})`);
        } else {
            console.log(`[Cron] Triggered at ${hour}:${minute.toString().padStart(2, '0')} KST (Day: ${dayOfWeek})`);
        }

        // Security check for unauthorized execution
        const CRON_SECRET = process.env.CRON_SECRET;
        const secretParam = searchParams.get('secret');
        if (!CRON_SECRET || secretParam !== CRON_SECRET) {
            console.error('[Cron] Unauthorized access attempt (Invalid or missing secret)');
            return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
        }

        // 0. Check if market is open (Mon-Fri only)
        if (dayOfWeek === 0 || dayOfWeek === 6) {
            const dayName = dayOfWeek === 0 ? 'Sunday' : 'Saturday';
            console.log(`[Cron] Market closed (${dayName}). Skipping execution.`);
            return NextResponse.json({
                success: true,
                skipped: true,
                reason: `Market closed on ${dayName}`,
                time: `${hour}:${minute.toString().padStart(2, '0')} KST`
            });
        }

        // 1. Check if scraping time (Removed hardcoded hours -> Run on trigger)
        // User manages schedule via Tasker (2분 간격)

        // 어느 워크플로로 보낼지는 src/lib/cron-target.ts가 정한다.
        // 여기 인라인으로 두면 라우트를 node --test로 import할 수 없어 아무도
        // 검증하지 못한다 — 2026-08-07에 정확히 그 모양으로 하루를 잃었다.
        const WORKFLOW_FILE = pickWorkflow(hour, minute);

        console.log(`[Cron] Trigger received (${hour}:${minute.toString().padStart(2, '0')} KST). Dispatching ${WORKFLOW_FILE}...`);

        if (!GITHUB_PAT) {
            console.error('[Cron] GITHUB_PAT is missing!');
            return NextResponse.json({
                error: 'Missing GITHUB_PAT',
                success: false
            }, { status: 500 });
        }

        try {
            const response = await axios.post(
                `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
                { ref: 'main' },
                {
                    headers: {
                        Authorization: `Bearer ${GITHUB_PAT}`,
                        Accept: 'application/vnd.github.v3+json',
                    },
                }
            );

            console.log(`[Cron] GitHub Actions triggered successfully. Status: ${response.status}`);
        } catch (githubError: any) {
            console.error('[Cron] GitHub API Error:', githubError.message);
            console.error('[Cron] Error details:', githubError.response?.data);

            return NextResponse.json({
                error: 'Failed to trigger GitHub Actions',
                details: githubError.message,
                githubResponse: githubError.response?.data,
                success: false
            }, { status: 500 });
        }

        return NextResponse.json({
            success: true,
            time: `${hour}:${minute.toString().padStart(2, '0')} KST`,
            dispatched: WORKFLOW_FILE,
            // 매매 트리거인지 토큰 선발급인지. 스크래핑은 여기서 직접 부르지
            // 않는다 — trading.yml이 10분 격자에서 scraper.yml을 깨운다.
            tradingTriggered: WORKFLOW_FILE === 'trading.yml'
        });

    } catch (error: any) {
        console.error('[Cron] Error:', error.message);
        return NextResponse.json({
            error: 'Cron execution failed',
            details: error.message
        }, { status: 500 });
    }
}
