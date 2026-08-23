import { NextResponse } from 'next/server';
import { getToken } from 'next-auth/jwt';
import { US_RESET_TARGETS, RESET_CSV_HEADER, buildResetState, validateUsCash } from '@/lib/us-sim-reset-targets';
import { commitFilesAtomically } from '@/lib/github-tree-commit';

export const dynamic = 'force-dynamic';

const OWNER = 'hoonnamkoong';
const REPO = 'stockbot';
const BRANCH = 'db-data';
const GITHUB_PAT = process.env.GITHUB_PAT || process.env.GITHUB_TOKEN;

export async function POST(request: Request) {
  const token = await getToken({ req: request as any, secret: process.env.NEXTAUTH_SECRET });
  if (!token) return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  if (!GITHUB_PAT) return NextResponse.json({ success: false, error: 'Server auth not configured' }, { status: 500 });

  let body: any;
  try { body = await request.json(); } catch { return NextResponse.json({ success: false, error: '잘못된 요청' }, { status: 400 }); }

  const v = validateUsCash(body?.cash);
  if (!v.ok) return NextResponse.json({ success: false, error: v.error }, { status: 400 });

  const stateJson = JSON.stringify(buildResetState(v.value), null, 2);
  const files = US_RESET_TARGETS.flatMap(t => ([
    { path: `data/${t.stateFile}`, content: stateJson },
    { path: `data/${t.csvFile}`, content: RESET_CSV_HEADER },
  ]));

  try {
    await commitFilesAtomically({
      owner: OWNER, repo: REPO, branch: BRANCH, token: GITHUB_PAT,
      message: `chore(us-sim): reset ${US_RESET_TARGETS.length} US simulators to $${v.value} (dashboard)`,
      files,
    });
  } catch (e: any) {
    return NextResponse.json({ success: false, error: `리셋 실패: ${e?.message ?? e}` }, { status: 500 });
  }

  return NextResponse.json({ success: true, cash: v.value, sims: US_RESET_TARGETS.map(t => t.id) });
}
