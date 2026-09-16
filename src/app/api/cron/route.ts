import { NextResponse } from 'next/server';
import axios from 'axios';
import { pickWorkflow, pickSideWorkflows } from '@/lib/cron-target';
import { authorizeCronRequest } from '@/lib/cron-auth';

export const dynamic = 'force-dynamic';
export const maxDuration = 60;

export async function GET(request: Request) {
    const GITHUB_PAT = process.env.GITHUB_PAT;
    const REPO_OWNER = 'hoonnamkoong';
    const REPO_NAME = 'stockbot';

    try {
        const urlStr = request.url || '';
        const parsedUrl = urlStr.startsWith('http') ? new URL(urlStr) : new URL(urlStr, 'http://localhost');
        const { searchParams } = parsedUrl;

        // Get current KST time (실제 시각만 쓴다 — hour/minute 디버그 파라미터는 프로덕션에
        // 살아 있던 시각 위조 경로였다)
        const now = new Date();
        const kstTime = new Date(now.getTime() + 9 * 60 * 60 * 1000);
        const hour = kstTime.getHours();
        const minute = kstTime.getMinutes();
        const dayOfWeek = kstTime.getDay(); // 0=Sun, 6=Sat

        console.log(`[Cron] Triggered at ${hour}:${minute.toString().padStart(2, '0')} KST (Day: ${dayOfWeek})`);

        // Security check for unauthorized execution.
        // 헤더(Authorization: Bearer <CRON_SECRET>)가 우선이다. 쿼리스트링 ?secret=은
        // 태스커 설정을 사용자가 헤더로 바꾸기 전까지 당분간 계속 허용한다 — 지금 끊으면
        // 실매매 트리거가 멈춘다. 대신 쓸 때마다 deprecated 경고를 로그에 남긴다.
        const CRON_SECRET = process.env.CRON_SECRET;
        const authHeader = request.headers.get('authorization');
        const secretParam = searchParams.get('secret');
        const authVerdict = authorizeCronRequest({ authHeader, secretParam, cronSecret: CRON_SECRET });
        if (!authVerdict.ok) {
            console.error('[Cron] Unauthorized access attempt (Invalid or missing secret)');
            return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
        }
        if (authVerdict.deprecated) {
            console.warn('[Cron] deprecated: 쿼리스트링 ?secret= 로 인증됨 — 태스커 설정을 Authorization 헤더로 옮겨라.');
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
        // 주 대상 말고 **추가로** 깨울 워크플로(장중 생존 감시). 주 대상을 갈라
        // 쓰지 않는다 — 그러면 그 틱의 매매 트리거가 사라진다.
        const SIDE_WORKFLOWS = pickSideWorkflows(hour, minute);

        console.log(`[Cron] Trigger received (${hour}:${minute.toString().padStart(2, '0')} KST). Dispatching ${WORKFLOW_FILE}...`);

        if (!GITHUB_PAT) {
            console.error('[Cron] GITHUB_PAT is missing!');
            return NextResponse.json({
                error: 'Missing GITHUB_PAT',
                success: false
            }, { status: 500 });
        }

        const dispatch = (file: string) => axios.post(
            `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${file}/dispatches`,
            { ref: 'main' },
            {
                headers: {
                    Authorization: `Bearer ${GITHUB_PAT}`,
                    Accept: 'application/vnd.github.v3+json',
                },
            }
        );

        // 돈 경로가 먼저다. 실패해도 여기서 바로 돌려보내지 않는다 —
        // **주 대상 dispatch가 실패한 순간이 감시가 가장 필요한 순간이고**,
        // 이 라우트의 500은 태스커 로그에만 남아 아무에게도 안 보인다.
        let primaryError: any = null;
        try {
            const response = await dispatch(WORKFLOW_FILE);
            console.log(`[Cron] GitHub Actions triggered successfully. Status: ${response.status}`);
        } catch (githubError: any) {
            primaryError = githubError;
            console.error('[Cron] GitHub API Error:', githubError.message);
            console.error('[Cron] Error details:', githubError.response?.data);
        }

        // 부수 dispatch 실패는 응답을 바꾸지 않는다. 감시자가 한 틱 안 깨는 것과
        // 매매 트리거를 실패로 돌려보내는 것은 무게가 다르다.
        const sideDispatched: string[] = [];
        for (const file of SIDE_WORKFLOWS) {
            try {
                await dispatch(file);
                sideDispatched.push(file);
                console.log(`[Cron] Side workflow dispatched: ${file}`);
            } catch (sideError: any) {
                console.error(`[Cron] Side dispatch failed (${file}):`, sideError.message);
            }
        }

        if (primaryError) {
            return NextResponse.json({
                error: 'Failed to trigger GitHub Actions',
                details: primaryError.message,
                githubResponse: primaryError.response?.data,
                sideDispatched,
                success: false
            }, { status: 500 });
        }

        return NextResponse.json({
            success: true,
            time: `${hour}:${minute.toString().padStart(2, '0')} KST`,
            dispatched: WORKFLOW_FILE,
            sideDispatched,
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
