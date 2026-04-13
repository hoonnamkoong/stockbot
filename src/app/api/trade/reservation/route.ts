import { NextResponse } from 'next/server';

/**
 * [V8.9.9.13] Reservation API (Remote Sync Version)
 * For Vercel (read-only), we sync reservations directly with GitHub db-data branch.
 */

const OWNER = 'hoonnamkoong';
const REPO = 'stockbot';
const FILE_PATH = 'data/reservations.json';
const BRANCH = 'db-data';
const GITHUB_PAT = process.env.GITHUB_PAT || process.env.GITHUB_TOKEN;

async function getFileFromGithub() {
    const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE_PATH}?ref=${BRANCH}`;
    const res = await fetch(url, {
        headers: { 
            'Authorization': `token ${GITHUB_PAT}`,
            'Accept': 'application/vnd.github.v3+json'
        },
        cache: 'no-store'
    });
    if (res.status === 404) return { sha: null, content: [] };
    const data = await res.json();
    const content = JSON.parse(Buffer.from(data.content, 'base64').toString('utf-8'));
    return { sha: data.sha, content };
}

export async function GET() {
    try {
        const { content } = await getFileFromGithub();
        return NextResponse.json({ success: true, data: content });
    } catch (error: any) {
        return NextResponse.json({ success: false, error: error.message }, { status: 500 });
    }
}

export async function POST(request: Request) {
    try {
        const body = await request.json();
        const { code, qty, price, side, time } = body;

        // 1. Get existing file
        const { sha, content } = await getFileFromGithub();

        const newRes = {
            id: `res_${Date.now()}`,
            code,
            qty,
            price,
            side,
            time: time || '15:15',
            status: 'PENDING',
            created_at: new Date().toISOString()
        };

        const updatedContent = [...content, newRes];
        const base64Content = Buffer.from(JSON.stringify(updatedContent, null, 2)).toString('base64');

        // 2. Push to GitHub
        const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE_PATH}`;
        const res = await fetch(url, {
            method: 'PUT',
            headers: { 
                'Authorization': `token ${GITHUB_PAT}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                message: `[V8.9.9.13] Add reservation: ${code} ${side}`,
                content: base64Content,
                sha: sha || undefined,
                branch: BRANCH
            })
        });

        if (!res.ok) {
            const error = await res.text();
            throw new Error(`GitHub API failed: ${error}`);
        }

        return NextResponse.json({ success: true, data: newRes });
    } catch (error: any) {
        console.error("[Reservation Error]", error);
        return NextResponse.json({ success: false, error: error.message }, { status: 500 });
    }
}
