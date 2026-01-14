import { NextResponse } from 'next/server';
import axios from 'axios';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
    const GITHUB_PAT = process.env.GITHUB_PAT;
    const REPO_OWNER = 'hoonnamkoong';
    const REPO_NAME = 'stockbot';
    const WORKFLOW_FILE = 'scraper.yml';

    if (!GITHUB_PAT) {
        return NextResponse.json({ error: 'Missing GITHUB_PAT' }, { status: 500 });
    }

    try {
        console.log(`[Cron] Triggering workflow ${WORKFLOW_FILE}...`);

        await axios.post(
            `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
            {
                ref: 'main',
            },
            {
                headers: {
                    Authorization: `Bearer ${GITHUB_PAT}`,
                    Accept: 'application/vnd.github.v3+json',
                },
            }
        );

        console.log(`[Cron] Trigger success.`);
        return NextResponse.json({ success: true, message: 'Scraper triggered successfully' });
    } catch (error: any) {
        console.error('Trigger failed:', error.response?.data || error.message);
        return NextResponse.json({
            error: 'Trigger failed',
            details: error.response?.data || error.message
        }, { status: 500 });
    }
}
