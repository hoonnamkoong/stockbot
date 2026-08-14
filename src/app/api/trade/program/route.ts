import { NextResponse } from 'next/server';
import { getToken } from 'next-auth/jwt';
import { tradeableSims } from '@/lib/sim-registry.generated';
import { getRealPortfolio } from '@/lib/kis-api';
import { computeTurnPnl, basisFromPositions, type ProgramTurn, type ProgramPosition, type LastTurnResult, type UnreconciledExit } from '@/lib/program-turn';
import { pushTurnHistory } from '@/lib/turn-history';
import { validateArmRequest } from '@/lib/trade-auth';
import { getRealizedProfitBuckets, summarizeRealizedBuckets } from '@/lib/kis-api';
import { kstTimestamp } from '@/lib/kst';

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

/**
 * 프론트 드롭다운이 기대하는 형태의 매매 가능 심 목록.
 *
 * name은 매니페스트 label이다. 예전 manifest-sims.ts는 description을 '-—(' 로 잘라
 * 이름을 만들어서, 실전 드롭다운에만 "심리 폭발형" 같은 대시보드와 다른 이름이 떴다.
 */
const programSimOptions = () =>
    tradeableSims().map((s) => ({ id: s.id, name: s.label, description: s.shortDesc }));

async function getConfig(): Promise<{ sha: string | null; content: any }> {
    const url = `https://api.github.com/repos/${OWNER}/${SECRET_REPO}/contents/${CONFIG_PATH}?ref=${SECRET_BRANCH}`;
    const res = await fetch(url, {
        headers: { Authorization: `token ${GITHUB_PAT}`, Accept: 'application/vnd.github.v3+json' },
        cache: 'no-store',
        // 상한이 없으면 GitHub이 매달릴 때 함수가 서버리스 타임아웃에 조용히 죽고,
        // OFF(kill-switch)가 아예 기록되지 않는다. 빠르게 실패시켜 사용자가 즉시 재시도하게 한다.
        signal: AbortSignal.timeout(5000),
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

/**
 * 표시용 계산이 kill-switch를 지연시키지 못하게 하는 하드 데드라인.
 * fetch 자체를 취소하진 못하지만(매달린 소켓은 그대로 뜬다), 핸들러는 폴백을 들고
 * 즉시 putConfig로 진행한다 → OFF 지연이 상수로 묶인다.
 */
function withDeadline<T>(p: Promise<T>, ms: number, fallback: T): Promise<T> {
    return Promise.race([
        p.catch(() => fallback),
        new Promise<T>((resolve) => setTimeout(() => resolve(fallback), ms)),
    ]);
}

/** 턴 동결/스냅샷 등 '표시용' 계산 전체에 걸리는 상한(ms). putConfig에는 걸지 않는다. */
const DISPLAY_DEADLINE_MS = 2500;

// ── 프로그램 매매 원장(program_positions.json) 읽기 전용 조회 ────────────
// 표시 전용 데이터이므로 실패해도 GET 전체를 막지 않고 빈 원장으로 대체한다(fail-safe).
// 단 ok로 '실패'와 '정상적으로 비어 있음'을 구분한다 — 동결 시 pnl:0으로 박제되면 안 되므로.
const POSITIONS_PATH = 'program_positions.json';

async function getPositions(): Promise<{
    ok: boolean;
    positions: Record<string, ProgramPosition>;
    realized_pnl: number;
    turn: ProgramTurn | null;
    unreconciled_exits: UnreconciledExit[];
    pnl_since: string | null;
}> {
    const empty = { positions: {}, realized_pnl: 0, turn: null, unreconciled_exits: [], pnl_since: null };
    try {
        const url = `https://api.github.com/repos/${OWNER}/${SECRET_REPO}/contents/${POSITIONS_PATH}?ref=${SECRET_BRANCH}`;
        const res = await fetch(url, {
            headers: { Authorization: `token ${GITHUB_PAT}`, Accept: 'application/vnd.github.v3+json' },
            cache: 'no-store',
            signal: AbortSignal.timeout(3000),
        });
        if (res.status === 404) return { ok: true, ...empty }; // 원장 미생성 = 정상(빈 원장)
        if (!res.ok) return { ok: false, ...empty };           // 그 외 HTTP 실패 = 조회 불가
        const data = await res.json();
        const content = JSON.parse(Buffer.from(data.content, 'base64').toString('utf-8'));
        return {
            ok: true,
            positions: content.positions && typeof content.positions === 'object' ? content.positions : {},
            realized_pnl: Number(content.realized_pnl) || 0,
            turn: content.turn && content.turn.id ? content.turn : null,
            // 실계좌에서 사라져 손익을 계상하지 못한 청산분. 비어 있지 않으면 누적 수익률은
            // 이 금액만큼 실제와 어긋난다(2026-07-08 진흥기업 등). 화면에서 감추지 않는다.
            unreconciled_exits: Array.isArray(content.unreconciled_exits) ? content.unreconciled_exits : [],
            // 누적 집계 시작일(yyyymmdd). 리셋 시점 이후만 KIS 실측과 비교해야 의미가 있다.
            pnl_since: typeof content.pnl_since === 'string' ? content.pnl_since : null,
        };
    } catch {
        return { ok: false, ...empty }; // 네트워크/파싱 실패 — non-blocking이되 '실패'로 신호
    }
}

/** 프로그램 원장 종목의 현재가 맵. 실패는 ok:false로 신호(빈 맵과 구분). */
async function getLivePrices(): Promise<{ ok: boolean; prices: Record<string, number> }> {
    try {
        const p: any = await getRealPortfolio();
        if (p?.error) return { ok: false, prices: {} };
        const prices: Record<string, number> = {};
        for (const h of p?.holdings || []) {
            if (h?.code) prices[h.code] = Number(h.price) || 0;
        }
        return { ok: true, prices };
    } catch {
        return { ok: false, prices: {} };
    }
}

/**
 * OFF 시점의 턴 손익 동결값을 만든다. 실패는 pnl:null + degraded로 정직하게 남긴다.
 * throw하지 않는다(getPositions/getLivePrices가 total). 호출부가 데드라인으로 감싼다.
 */
async function freezeTurn(cfgTurn: any, sim: string | null, endedAt: string, startedAt: string | undefined): Promise<LastTurnResult> {
    const base = { id: cfgTurn.id as string, ended_at: endedAt, started_at: startedAt, sim, capital: Number(cfgTurn.capital) || 0 };

    const { ok: ledgerOk, positions, turn } = await getPositions();
    if (!ledgerOk) return { ...base, pnl: null, by_tag: {}, fees: null, degraded: 'ledger_unavailable' };

    // 원장의 턴 id가 config와 다르면 이번 턴에 파이썬이 한 번도 안 돌았다(장 외 ON→OFF 등).
    // 이건 실패가 아니라 '거래가 없었다'는 뜻 — pnl:0이 정답이며 degraded를 붙이면 안 된다.
    const matched = turn && turn.id === cfgTurn.id ? turn : null;
    // `|| 0`이 아니라 이 순서다 — 원장을 못 읽은 것(null)과 거래가 없어 0원인 것을
    // 합치면 안 된다. 0원은 값이고 null은 '모른다'다.
    const fees = matched ? Number(matched.fees_realized ?? 0) : 0;
    if (!matched) return { ...base, pnl: 0, by_tag: {}, fees };

    const capital = Number(matched.capital) || base.capital;
    const held = Object.keys(positions).length > 0;
    const { ok: pricesOk, prices } = await getLivePrices();
    // 보유 종목이 있는데 그중 어느 것도 양수 시세를 못 얻었으면 사실상 조회 실패다
    // (getLivePrices는 성공 응답에 빈 holdings/0가만 와도 ok:true를 주므로 별도로 걸러야 한다).
    const noUsablePrice = held && !Object.keys(positions).some((c) => Number(prices[c]) > 0);
    // 보유 종목이 없으면 시세가 없어도 확정분(by_tag)만으로 손익이 정확하다.
    if (held && (!pricesOk || noUsablePrice)) return { ...base, capital, pnl: null, by_tag: {}, fees, degraded: 'prices_unavailable' };

    const { pnl, byTag } = computeTurnPnl(matched, positions, prices);
    return { ...base, capital, pnl, by_tag: byTag, fees };
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
        const sims = programSimOptions();
        const validIds = new Set(sims.map((s) => s.id));
        // selected_sim이 현재 매매 가능 목록에 없으면 무효(파이프라인도 OFF 취급)
        const selectedValid = !!content.selected_sim && validIds.has(content.selected_sim);
        const { ok: ledgerOk, positions, realized_pnl, turn, unreconciled_exits: unreconciledExits,
                pnl_since: pnlSince } = await getPositions();

        // [실측 대조] 원장의 realized_pnl은 주문가 추정치로 쌓은 값이라 실제 체결가와 어긋나고,
        // 수동 청산은 아예 빠진다. KIS가 확정한 실현손익(TTTC8715R)을 나란히 가져와 비교한다.
        // 계좌 전체 기준이므로 프로그램 외 매매가 있으면 그만큼 다르다 — 화면에서 그렇게 라벨한다.
        const kisRealized = await withDeadline((async (): Promise<{ ok: boolean; total: number } | null> => {
            if (!pnlSince) return null;                       // 집계 시작일이 없으면 비교 구간을 정할 수 없다
            const today = kstTimestamp().slice(0, 10).replace(/-/g, '');
            const { ok, buckets } = await getRealizedProfitBuckets(pnlSince, today);
            // 조회 실패면 '측정 불가'. 조회는 됐는데 매도가 없으면 0원이다 —
            // 둘을 합치면 진짜 조회 실패를 알아챌 방법이 사라진다.
            return summarizeRealizedBuckets(ok, buckets);
        })(), DISPLAY_DEADLINE_MS, null);
        // 진행 중인 턴은 config가 정의한다(ON 시 route가 연다). 원장 turn은 파이썬만 쓰고
        // OFF 시 지워지지 않으므로, id가 config와 같을 때만 채택한다(stale 방지).
        //
        // 아직 파이썬이 한 번도 안 돈 턴(ON 직후 ~ 다음 파이프라인 런, 또는 장 외 시간에 ON)은
        // 원장에 turn이 없다. 이때 null을 주면 사용자가 방금 켠 턴이 화면에서 사라진다 —
        // config의 opening_basis·capital만으로도 손익은 계산 가능하므로 그것으로 턴을 구성한다.
        // 기준가는 매입 평단이다(파이썬 new_turn과 동일 규칙) — 여기서도 그 값을 그대로 쓴다.
        // active_tag: null이 '아직 파이썬 미실행'의 신호다(원장에 저장된 턴은 항상 태그가 있다).
        const cfgTurn = content.turn;
        let liveTurn: ProgramTurn | null = null;
        if (content.enabled && cfgTurn?.id) {
            liveTurn = turn && turn.id === cfgTurn.id
                ? turn
                : {
                    id: cfgTurn.id,
                    capital: Number(cfgTurn.capital) || 0,
                    basis: cfgTurn.opening_basis || {},
                    by_tag: {},
                    active_tag: null,
                };
        }
        return NextResponse.json({
            enabled: !!content.enabled,
            selected_sim: content.selected_sim ?? null,
            budget: Number(content.budget) || 0,
            selected_valid: selectedValid,
            updated_at: content.updated_at ?? null,
            sims, // 프론트 드롭다운 재사용
            ledger_ok: ledgerOk, // 원장 조회 성공 여부 — false면 아래 값들은 '측정 불가'(0이 아님)
            positions, // 프로그램 원장 포지션(code -> {name, quantity, avg_price, tag})
            realized_pnl, // 프로그램 누적 실현손익(원)
            turn: liveTurn, // 진행 중인 턴(config와 원장이 같은 턴을 가리킬 때만) — 프론트가 실시간 손익 계산
            last_turn_result: content.last_turn_result ?? null, // OFF 시 동결된 직전 턴
            turn_history: Array.isArray(content.turn_history) ? content.turn_history : [],
            unreconciled_exits: unreconciledExits, // 손익 미계상 청산분 — 있으면 수익률이 실제와 어긋난다
            pnl_since: pnlSince,                   // 누적 집계 시작일(yyyymmdd)
            // KIS 확정 실현손익(계좌 전체). null이면 조회 못 함 → 화면은 '측정 불가'
            kis_realized_pnl: kisRealized && kisRealized.ok ? kisRealized.total : null,
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
            const now = kstTimestamp();
            // [턴 동결] OFF를 누른 순간의 턴 손익을 박제한다. OFF 이후의 시세 변동은
            // 어느 턴의 성과도 아니므로 섞이지 않는다.
            // 계산 전체에 하드 데드라인을 건다 — 실패든 hang이든 kill-switch를 지연/차단할 수 없다.
            // 계산이 불가능했으면 pnl:0이 아니라 pnl:null+degraded로 남긴다(가짜 0원 턴 금지).
            let lastTurnResult: LastTurnResult | null = content.last_turn_result ?? null;
            const cfgTurn = content.turn;
            if (cfgTurn?.id) {
                const sim: string | null = content.selected_sim ?? null;
                const capital = Number(cfgTurn.capital) || 0;
                const frozen = await withDeadline(freezeTurn(cfgTurn, sim, now, cfgTurn.started_at), DISPLAY_DEADLINE_MS, null);
                lastTurnResult = frozen ?? {
                    // 데드라인 초과 = 원장이 멀쩡한데 조회가 느렸을 수도 있다 → ledger_unavailable과 구분
                    id: cfgTurn.id, ended_at: now, started_at: cfgTurn.started_at, sim, capital,
                    pnl: null, by_tag: {}, fees: null, degraded: 'timeout',
                };
            }
            const next = { ...content, enabled: false, updated_at: now,
                updated_by: (token as any).email || (token as any).name || 'user',
                turn: null, last_turn_result: lastTurnResult,
                turn_history: lastTurnResult
                    ? pushTurnHistory(content.turn_history, lastTurnResult)
                    : (content.turn_history ?? []) };
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

        // selected_sim 화이트리스트 + 예산 검증 (임의 id 차단, fail-closed).
        // 판정은 src/lib/trade-auth.ts에 있다 — 라우트 안에서는 테스트가 닿지 않는다.
        const armed = validateArmRequest({
            selectedSim: selected_sim,
            budget,
            tradeableIds: tradeableSims().map((s) => s.id),
        });
        if (!armed.ok) {
            return NextResponse.json({ success: false, error: armed.error }, { status: 400 });
        }
        const { sim, budget: budgetNum } = armed;

        const now = kstTimestamp();

        // [턴 열기] 기준가는 매입 평단이다(basisFromPositions 주석 참고) — 시세 조회가 필요 없어졌다.
        // 잔고 조회가 실패해도 ON은 정상 진행 — 기준가는 파이썬 첫 실행 때 채워진다.
        // ON은 fail-open이지만 OFF와 같은 hang 노출이 있으므로 동일 데드라인을 건다.
        // (진행된 만큼만 turn에 반영되고, 나머지는 기본값 그대로 ON 진행)
        // IIFE는 turn을 in-place mutate하지 않고 값을 반환한다 — 이 await 완료 전에는
        // turn이 아직 존재하지 않으므로, 데드라인이 이겨 백그라운드에서 계속 도는 fetch가
        // 나중에 끝나도 이미 구성된 turn을 건드릴 수 없다.
        const opened = await withDeadline((async () => {
            const { ok: ledgerOk, positions, realized_pnl } = await getPositions();
            // 조회 실패/데드라인 초과 시 capital은 falsy(0)로 남긴다 — 그럴듯한 값을 지어내는 대신
            // 파이썬의 `cfg_turn.get('capital') or effective_budget` 폴백이 채우게 한다.
            const capital = ledgerOk ? budgetNum + realized_pnl : 0;   // 턴 시작 유효자본 = 이 턴에 실제로 굴릴 돈
            // 기준가는 매입 평단이다(basisFromPositions 주석 참고). 시세 조회가 필요 없어졌다.
            return { capital, opening_basis: basisFromPositions(positions) };
        })(), DISPLAY_DEADLINE_MS, { capital: 0, opening_basis: {} });

        const turn: any = { id: new Date().toISOString(), started_at: now, capital: opened.capital, opening_basis: opened.opening_basis };

        const next = {
            ...content,
            enabled: true,
            selected_sim: sim,
            budget: budgetNum,
            turn,
            updated_at: now,
            updated_by: (token as any).email || (token as any).name || 'user',
        };
        await putConfig(next, sha, `program-trading: ON ${sim} budget=${budgetNum}`);

        return NextResponse.json({ success: true, enabled: next.enabled, selected_sim: next.selected_sim, budget: next.budget });
    } catch (error: any) {
        return NextResponse.json({ success: false, error: error.message }, { status: 500 });
    }
}
