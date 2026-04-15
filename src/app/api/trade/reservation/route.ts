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
    const rawContent = Buffer.from(data.content, 'base64').toString('utf-8').trim();
    const content = JSON.parse(rawContent);
    return { sha: data.sha, content };
}

export async function GET() {
    try {
        const { content } = await getFileFromGithub();
        
        // [V8.9.9.22 Fix] 한국 시간(KST) 기준 오늘 날짜가 지난 예약은 필터링 (자동 만료)
        const nowKst = new Date(Date.now() + 9 * 60 * 60 * 1000);
        const todayStr = nowKst.toISOString().split('T')[0]; // YYYY-MM-DD
        
        const activeReservations = content.filter((res: any) => {
            if (!res.created_at) return true;
            const resDate = res.created_at.split(' ')[0];
            return resDate >= todayStr;
        });

        return NextResponse.json({ success: true, data: activeReservations });
    } catch (error: any) {
        return NextResponse.json({ success: false, error: error.message }, { status: 500 });
    }
}

export async function DELETE(request: Request) {
    try {
        const { searchParams } = new URL(request.url);
        const id = searchParams.get('id');
        if (!id) return NextResponse.json({ success: false, error: 'ID is required' }, { status: 400 });

        // 1. 기존 파일 및 SHA 획득
        const { sha, content } = await getFileFromGithub();

        // 2. 해당 ID 제외
        const updatedContent = content.filter((res: any) => res.id !== id);

        if (content.length === updatedContent.length) {
            return NextResponse.json({ success: false, error: 'Reservation not found' }, { status: 404 });
        }

        // 3. GitHub 업데이트
        const base64Content = Buffer.from(JSON.stringify(updatedContent, null, 2)).toString('base64');
        const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE_PATH}`;
        const res = await fetch(url, {
            method: 'PUT',
            headers: { 
                'Authorization': `token ${GITHUB_PAT}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                message: `[V8.9.9.22] Delete reservation: ${id}`,
                content: base64Content,
                sha: sha,
                branch: BRANCH
            })
        });

        if (!res.ok) throw new Error('GitHub sync failed during deletion');

        return NextResponse.json({ success: true });
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
            created_at: new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().replace('Z', '').replace('T', ' ').split('.')[0]
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
