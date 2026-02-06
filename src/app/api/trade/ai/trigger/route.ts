import { NextResponse } from 'next/server';
import { exec } from 'child_process';
import path from 'path';

export const dynamic = 'force-dynamic'; // No caching

export async function GET(request: Request) {
    try {
        console.log('[AI Trader] Trigger request received.');

        const GITHUB_PAT = process.env.GITHUB_PAT;
        const REPO_OWNER = 'hoonnamkoong';
        const REPO_NAME = 'stockbot';
        const WORKFLOW_FILE = 'sentinel_v.yml';

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
