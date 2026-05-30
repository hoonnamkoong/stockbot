import { NextResponse } from 'next/server';

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

        // Security check for unauthorized execution
        const CRON_SECRET = process.env.CRON_SECRET;
        const secretParam = searchParams.get('secret');
        if (!CRON_SECRET || secretParam !== CRON_SECRET) {
            console.error('[AI Trader] Unauthorized access attempt (Invalid or missing secret)');
            return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
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
