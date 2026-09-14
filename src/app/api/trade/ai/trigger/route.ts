import { NextResponse } from 'next/server';
import { authorizeCronRequest } from '@/lib/cron-auth';

export const dynamic = 'force-dynamic'; // No caching

export async function GET(request: Request) {
    try {
        console.log('[AI Trader] Trigger request received.');

        const GITHUB_PAT = process.env.GITHUB_PAT;
        const REPO_OWNER = 'hoonnamkoong';
        const REPO_NAME = 'stockbot';
        const WORKFLOW_FILE = 'sentinel_v.yml';

        // Parse search params for secret
        const urlStr = request.url || '';
        const parsedUrl = urlStr.startsWith('http') ? new URL(urlStr) : new URL(urlStr, 'http://localhost');
        const { searchParams } = parsedUrl;

        // Security check for unauthorized execution.
        // 헤더(Authorization: Bearer <CRON_SECRET>)가 우선이다. 쿼리스트링 ?secret=은
        // 태스커 설정을 사용자가 헤더로 바꾸기 전까지 당분간 계속 허용한다 — 지금 끊으면
        // 실매매 트리거가 멈춘다. 대신 쓸 때마다 deprecated 경고를 로그에 남긴다.
        const CRON_SECRET = process.env.CRON_SECRET;
        const authHeader = request.headers.get('authorization');
        const secretParam = searchParams.get('secret');
        const authVerdict = authorizeCronRequest({ authHeader, secretParam, cronSecret: CRON_SECRET });
        if (!authVerdict.ok) {
            console.error('[AI Trader] Unauthorized access attempt (Invalid or missing secret)');
            return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
        }
        if (authVerdict.deprecated) {
            console.warn('[AI Trader] deprecated: 쿼리스트링 ?secret= 로 인증됨 — 태스커 설정을 Authorization 헤더로 옮겨라.');
        }

        if (!GITHUB_PAT) {
            throw new Error('Missing GITHUB_PAT env var');
        }

        const axios = require('axios');
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

        console.log(`[AI Trader] Triggered GitHub Action. Status: ${response.status}`);

        return NextResponse.json({
            success: true,
            message: 'Sentinel-V AI Trader triggered via GitHub Actions',
            workflow: WORKFLOW_FILE
        });

    } catch (error: any) {
        return NextResponse.json({
            error: 'Failed to trigger AI Trader',
            details: error.message
        }, { status: 500 });
    }
}
