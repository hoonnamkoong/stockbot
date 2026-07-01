import { NextResponse } from 'next/server';
import { getToken } from 'next-auth/jwt';
import { fetchTradeableSims } from '@/lib/manifest-sims';

export const dynamic = 'force-dynamic';

/**
 * 프로그램 매매 config API
 * - 저장소: 비공개 레포 stockbot-secret 의 program_trading.json (매매 posture 비공개)
 * - GET: 세션 필요. 현재 config + selected_sim 유효성 반환.
 * - POST OFF(enabled:false): 세션만으로 즉시 kill-switch, enabled 필드만 변경(sim/budget 불변).
 * - POST ON(enabled:true) 또는 sim/budget 변경: 세션 + PIN + 레이트리밋. 화이트리스트 검증,
 *   budget>0 필수. PIN 5회 실패 시 10분 잠금(program_pin_lockout.json).
 * - 프론트가 유일한 writer. 파이프라인은 읽기만(race 방지).
 */

const OWNER = 'hoonnamkoong';
const SECRET_REPO = 'stockbot-secret';
const SECRET_BRANCH = 'main';
const CONFIG_PATH = 'program_trading.json';
const GITHUB_PAT = process.env.GITHUB_PAT || process.env.GITHUB_TOKEN;

const DEFAULT_CONFIG = { enabled: false, selected_sim: null as string | null, budget: 0 };

async function getConfig(): Promise<{ sha: string | null; content: any }> {
    const url = `https://api.github.com/repos/${OWNER}/${SECRET_REPO}/contents/${CONFIG_PATH}?ref=${SECRET_BRANCH}`;
    const res = await fetch(url, {
        headers: { Authorization: `token ${GITHUB_PAT}`, Accept: 'application/vnd.github.v3+json' },
        cache: 'no-store',
    });
    if (res.status === 404) return { sha: null, content: { ...DEFAULT_CONFIG } };
    if (!res.ok) throw new Error(`config read ${res.status}`);
    const data = await res.json();
    const content = JSON.parse(Buffer.from(data.content, 'base64').toString('utf-8'));
    return { sha: data.sha, content: { ...DEFAULT_CONFIG, ...content } };
}

async function putConfig(content: any, sha: string | null, message: string) {
    const url = `https://api.github.com/repos/${OWNER}/${SECRET_REPO}/contents/${CONFIG_PATH}`;
    const body = Buffer.from(JSON.stringify(content, null, 2)).toString('base64');
    const res = await fetch(url, {
        method: 'PUT',
        headers: { Authorization: `token ${GITHUB_PAT}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, content: body, sha: sha || undefined, branch: SECRET_BRANCH }),
    });
    if (!res.ok) throw new Error(`config write ${res.status}: ${await res.text()}`);
}

// ── PIN 무차별 대입 방어 (파일 기반 카운터, secret repo) ─────────────────
// 프로그램 매매 ON은 4자리 PIN 하나가 무인 자동매매를 여는 유일한 문 → 브루트포스 방어 필수.
const PIN_LOCK_PATH = 'program_pin_lockout.json';
const PIN_MAX_ATTEMPTS = 5;
const PIN_LOCKOUT_MIN = 10;

async function getPinLock(): Promise<{ sha: string | null; content: { fails: number; locked_until: string | null } }> {
    const url = `https://api.github.com/repos/${OWNER}/${SECRET_REPO}/contents/${PIN_LOCK_PATH}?ref=${SECRET_BRANCH}`;
    const res = await fetch(url, {
        headers: { Authorization: `token ${GITHUB_PAT}`, Accept: 'application/vnd.github.v3+json' },
        cache: 'no-store',
    });
    if (res.status === 404) return { sha: null, content: { fails: 0, locked_until: null } };
    if (!res.ok) return { sha: null, content: { fails: 0, locked_until: null } }; // 조회 실패는 non-blocking
    const data = await res.json();
    const content = JSON.parse(Buffer.from(data.content, 'base64').toString('utf-8'));
    return { sha: data.sha, content: { fails: content.fails ?? 0, locked_until: content.locked_until ?? null } };
}

async function putPinLock(content: any, sha: string | null) {
    const url = `https://api.github.com/repos/${OWNER}/${SECRET_REPO}/contents/${PIN_LOCK_PATH}`;
    const body = Buffer.from(JSON.stringify(content, null, 2)).toString('base64');
    await fetch(url, {
        method: 'PUT',
        headers: { Authorization: `token ${GITHUB_PAT}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: 'pin lockout update', content: body, sha: sha || undefined, branch: SECRET_BRANCH }),
    });
}

async function checkPinRateLimit(): Promise<{ allowed: boolean; retryAfterMin: number }> {
    try {
        const { content } = await getPinLock();
        if (content.locked_until) {
            const until = new Date(content.locked_until).getTime();
            if (Date.now() < until) {
                return { allowed: false, retryAfterMin: Math.ceil((until - Date.now()) / 60000) };
            }
        }
        return { allowed: true, retryAfterMin: 0 };
    } catch {
        return { allowed: true, retryAfterMin: 0 }; // 조회 실패 시 잠금 판단 불가 → 통과(가용성 우선, PIN 자체가 여전히 방어선)
    }
}

async function recordPinFailure(): Promise<void> {
    try {
        const { sha, content } = await getPinLock();
        const fails = content.fails + 1;
        const locked_until = fails >= PIN_MAX_ATTEMPTS
            ? new Date(Date.now() + PIN_LOCKOUT_MIN * 60000).toISOString()
            : content.locked_until;
        await putPinLock({ fails: fails >= PIN_MAX_ATTEMPTS ? 0 : fails, locked_until }, sha);
    } catch { /* 카운터 갱신 실패는 non-blocking */ }
}

async function clearPinFailures(): Promise<void> {
    try {
        const { sha, content } = await getPinLock();
        if (content.fails > 0 || content.locked_until) {
            await putPinLock({ fails: 0, locked_until: null }, sha);
        }
    } catch { /* non-blocking */ }
}

export async function GET(request: Request) {
    try {
        const token = await getToken({ req: request as any, secret: process.env.NEXTAUTH_SECRET });
        if (!token) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

        const { content } = await getConfig();
        const sims = await fetchTradeableSims();
        const validIds = new Set(sims.map((s) => s.id));
        // selected_sim이 현재 매매 가능 목록에 없으면 무효(파이프라인도 OFF 취급)
        const selectedValid = !!content.selected_sim && validIds.has(content.selected_sim);
        return NextResponse.json({
            enabled: !!content.enabled,
            selected_sim: content.selected_sim ?? null,
            budget: Number(content.budget) || 0,
            selected_valid: selectedValid,
            updated_at: content.updated_at ?? null,
            sims, // 프론트 드롭다운 재사용
        });
    } catch (error: any) {
        return NextResponse.json({ error: error.message }, { status: 500 });
    }
}

export async function POST(request: Request) {
    try {
        // 인증: 세션 + PIN (수동 주문과 동일 강도)
        const token = await getToken({ req: request as any, secret: process.env.NEXTAUTH_SECRET });
        if (!token) return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });

        const body = await request.json();
        const { enabled, selected_sim, budget, pin } = body;
        const wantEnabled = !!enabled;

        const { sha, content } = await getConfig();

        // [보안 교정] OFF(kill-switch)는 세션만으로 즉시 허용하되, 'enabled' 필드만 변경한다.
        // selected_sim/budget은 절대 함께 덮어쓰지 않는다 — 낡은 브라우저 탭이나 스크립트가
        // enabled:false 요청에 실수로/악의로 실은 오래된 sim/budget 값이 PIN 검증 없이
        // 저장되는 것을 원천 차단(다음 PIN-ON 시 사용자 모르게 다른 값으로 무장되는 것 방지).
        if (!wantEnabled) {
            const now = new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().replace('T', ' ').split('.')[0];
            const next = { ...content, enabled: false, updated_at: now,
                updated_by: (token as any).email || (token as any).name || 'user' };
            await putConfig(next, sha, 'program-trading: OFF (kill-switch)');
            return NextResponse.json({ success: true, enabled: false, selected_sim: next.selected_sim, budget: next.budget });
        }

        // 이 아래는 ON(arm) 또는 sim/budget 변경 — 항상 PIN 필요.
        const tradePin = process.env.TRADE_PIN;
        if (!tradePin) return NextResponse.json({ success: false, error: 'Server auth not configured' }, { status: 500 });
        const pinCheck = await checkPinRateLimit();
        if (!pinCheck.allowed) {
            return NextResponse.json({ success: false, error: `PIN 시도 제한 초과. ${pinCheck.retryAfterMin}분 후 재시도하세요.` }, { status: 429 });
        }
        if (pin !== tradePin) {
            await recordPinFailure();
            return NextResponse.json({ success: false, error: 'Invalid TRADING AUTH' }, { status: 403 });
        }
        await clearPinFailures();

        // selected_sim 화이트리스트 검증 (임의 id 차단)
        const sims = await fetchTradeableSims();
        const validIds = new Set(sims.map((s) => s.id));
        const sim = selected_sim && validIds.has(selected_sim) ? selected_sim : null;
        const budgetNum = Math.max(0, Math.floor(Number(budget) || 0));

        // ON은 유효 sim AND budget>0 일 때만 허용 (fail-closed)
        if (!sim || budgetNum <= 0) {
            return NextResponse.json({
                success: false,
                error: !sim ? '유효한 매매 심을 선택해야 켤 수 있습니다.' : '프로그램 예산(>0)을 설정해야 켤 수 있습니다.',
            }, { status: 400 });
        }

        const now = new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().replace('T', ' ').split('.')[0];
        const next = {
            ...content,
            enabled: true,
            selected_sim: sim,
            budget: budgetNum,
            updated_at: now,
            updated_by: (token as any).email || (token as any).name || 'user',
        };
        await putConfig(next, sha, `program-trading: ON ${sim} budget=${budgetNum}`);

        return NextResponse.json({ success: true, enabled: next.enabled, selected_sim: next.selected_sim, budget: next.budget });
    } catch (error: any) {
        return NextResponse.json({ success: false, error: error.message }, { status: 500 });
    }
}
