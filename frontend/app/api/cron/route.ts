import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic'; // Ensure this runs every time

export async function GET() {
    console.log('[Cron] Triggering GitHub Action...');

    // 1. Check for Personal Access Token
    const GITHUB_PAT = process.env.GITHUB_PAT;
    if (!GITHUB_PAT) {
        console.error('[Cron] Missing GITHUB_PAT environment variable');
        return NextResponse.json({ success: false, error: 'Server Configuration Error: Missing GITHUB_PAT' }, { status: 500 });
    }

    const REPO_OWNER = 'hoonnamkoong';
    const REPO_NAME = 'stockbot';
    const WORKFLOW_ID = 'scraper.yml';

    try {
        // 2. Call GitHub API to Dispatch Workflow
        const response = await fetch(`https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${WORKFLOW_ID}/dispatches`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${GITHUB_PAT}`,
                'Accept': 'application/vnd.github.v3+json',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                ref: 'main' // Trigger on main branch
            }),
        });

        // 3. Handle Response
        if (response.ok) {
            console.log('[Cron] Successfully triggered GitHub Workflow');
            return NextResponse.json({ success: true, message: 'StockBot Scraper Triggered via Vercel Cron' });
        } else {
            const errorText = await response.text();
            console.error(`[Cron] GitHub API Failed: ${response.status} ${errorText}`);
            return NextResponse.json({ success: false, error: `GitHub API Error: ${errorText}` }, { status: response.status });
        }

    } catch (error: any) {
        console.error('[Cron] Execution Error:', error);
        return NextResponse.json({ success: false, error: error.message }, { status: 500 });
    }
}
