# 시뮬레이터 리셋 버튼 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 대시보드에서 예수금을 입력하고 리셋하면 매매 심 9개(Sim1~7 + Sim10)가 동일 예수금 클린슬레이트로 초기화되어 재경쟁한다.

**Architecture:** 순수 로직(리셋 대상 목록·상태 페이로드 빌더·검증)을 `src/lib/sim-reset-targets.ts`에 분리하고 Node 네이티브 TS 테스트로 검증. 신규 API 라우트 `POST /api/simulation/reset`가 로그인 세션 확인 후 GitHub Git Data API로 db-data 브랜치에 **단일 원자 커밋**(9 상태 JSON 초기화 + 9 거래기록 CSV 헤더화)을 만든다. TradeClient에 예수금 입력·리셋 버튼·확인 모달을 추가한다.

**Tech Stack:** Next.js(App Router, TS), next-auth(getToken), GitHub REST(Git Data API), Node v26 네이티브 TS 테스트(`node --test`), Mantine UI.

## Global Constraints

- 대상 심 9개(id/상태파일/CSV): sim1=sim_psych, sim2=sim_spillover, sim3=sim_risk, sim4=sim_bull, sim4_daytrading=sim_bulldaytrade, sim5=sim_sideways, sim6=sim_bear, sim7=sim_reportfollower, sim10=sim_orchestrator. Sim0(리베로)·레거시 심·실계좌는 **제외**.
- 상태 JSON shape는 `base_simulator.reset_state()`와 정확히 일치: `{initial_cash, cash, invested:0, portfolio:{}, peak_nav, total_fees:0, history:[cash], daily_trades:[], market_index_healthy:true, cooldown_codes:{}}` (initial_cash=cash=peak_nav=입력 예수금).
- CSV 헤더(정확히, UTF-8 BOM 포함): `﻿timestamp,symbol,action,price,quantity,total_amount,reason`
- 예수금 검증: 정수, `100_000 ≤ cash ≤ 1_000_000_000`.
- GitHub: OWNER=`hoonnamkoong`, REPO=`stockbot`(public), BRANCH=`db-data`, 경로 접두 `data/`. 인증 `process.env.GITHUB_PAT || process.env.GITHUB_TOKEN`. 세션 `getToken({ req, secret: process.env.NEXTAUTH_SECRET })`.
- PIN 없음(가상 자본). 단 미인증 401.

---

### Task 1: 리셋 순수 로직 (대상 목록·페이로드·검증)

**Files:**
- Create: `src/lib/sim-reset-targets.ts`
- Test: `src/lib/sim-reset-targets.test.ts`

**Interfaces:**
- Produces:
  - `RESET_TARGETS: { id: string; stateFile: string; csvFile: string }[]` (9개)
  - `RESET_CSV_HEADER: string` (BOM 포함 헤더 1행, 끝에 `\n`)
  - `buildResetState(cash: number): object` — reset_state shape 반환
  - `validateCash(cash: unknown): { ok: true; value: number } | { ok: false; error: string }`

- [ ] **Step 1: 실패 테스트 작성**

`src/lib/sim-reset-targets.test.ts`:
```ts
import { test } from 'node:test';
import assert from 'node:assert';
import { RESET_TARGETS, RESET_CSV_HEADER, buildResetState, validateCash } from './sim-reset-targets.ts';

test('대상 심 9개 + 파일명 규칙', () => {
  assert.equal(RESET_TARGETS.length, 9);
  const ids = RESET_TARGETS.map(t => t.id);
  assert.deepEqual(ids, ['sim1','sim2','sim3','sim4','sim4_daytrading','sim5','sim6','sim7','sim10']);
  const bear = RESET_TARGETS.find(t => t.id === 'sim6')!;
  assert.equal(bear.stateFile, 'sim_bear_state.json');
  assert.equal(bear.csvFile, 'trade_history_sim_bear.csv');
});

test('CSV 헤더는 BOM + 정확한 컬럼', () => {
  assert.equal(RESET_CSV_HEADER, '﻿timestamp,symbol,action,price,quantity,total_amount,reason\n');
});

test('buildResetState는 reset_state shape', () => {
  const s: any = buildResetState(3_000_000);
  assert.equal(s.initial_cash, 3_000_000);
  assert.equal(s.cash, 3_000_000);
  assert.equal(s.peak_nav, 3_000_000);
  assert.equal(s.invested, 0);
  assert.equal(s.total_fees, 0);
  assert.deepEqual(s.portfolio, {});
  assert.deepEqual(s.history, [3_000_000]);
  assert.deepEqual(s.daily_trades, []);
  assert.equal(s.market_index_healthy, true);
  assert.deepEqual(s.cooldown_codes, {});
});

test('validateCash 경계값', () => {
  assert.equal(validateCash(3_000_000).ok, true);
  assert.equal(validateCash(100_000).ok, true);
  assert.equal(validateCash(1_000_000_000).ok, true);
  assert.equal(validateCash(99_999).ok, false);
  assert.equal(validateCash(1_000_000_001).ok, false);
  assert.equal(validateCash(3_000_000.5).ok, false);
  assert.equal(validateCash('3000000').ok, false);
  assert.equal(validateCash(NaN).ok, false);
});
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `node --test src/lib/sim-reset-targets.test.ts`
Expected: FAIL — `Cannot find module './sim-reset-targets.ts'`

- [ ] **Step 3: 최소 구현**

`src/lib/sim-reset-targets.ts`:
```ts
export interface ResetTarget { id: string; stateFile: string; csvFile: string; }

export const RESET_TARGETS: ResetTarget[] = [
  { id: 'sim1', stateFile: 'sim_psych_state.json', csvFile: 'trade_history_sim_psych.csv' },
  { id: 'sim2', stateFile: 'sim_spillover_state.json', csvFile: 'trade_history_sim_spillover.csv' },
  { id: 'sim3', stateFile: 'sim_risk_state.json', csvFile: 'trade_history_sim_risk.csv' },
  { id: 'sim4', stateFile: 'sim_bull_state.json', csvFile: 'trade_history_sim_bull.csv' },
  { id: 'sim4_daytrading', stateFile: 'sim_bulldaytrade_state.json', csvFile: 'trade_history_sim_bulldaytrade.csv' },
  { id: 'sim5', stateFile: 'sim_sideways_state.json', csvFile: 'trade_history_sim_sideways.csv' },
  { id: 'sim6', stateFile: 'sim_bear_state.json', csvFile: 'trade_history_sim_bear.csv' },
  { id: 'sim7', stateFile: 'sim_reportfollower_state.json', csvFile: 'trade_history_sim_reportfollower.csv' },
  { id: 'sim10', stateFile: 'sim_orchestrator_state.json', csvFile: 'trade_history_sim_orchestrator.csv' },
];

export const RESET_CSV_HEADER = '﻿timestamp,symbol,action,price,quantity,total_amount,reason\n';

export function buildResetState(cash: number): Record<string, unknown> {
  return {
    initial_cash: cash, cash, invested: 0, portfolio: {}, peak_nav: cash,
    total_fees: 0, history: [cash], daily_trades: [],
    market_index_healthy: true, cooldown_codes: {},
  };
}

export function validateCash(cash: unknown): { ok: true; value: number } | { ok: false; error: string } {
  if (typeof cash !== 'number' || !Number.isInteger(cash)) {
    return { ok: false, error: '예수금은 정수여야 합니다' };
  }
  if (cash < 100_000 || cash > 1_000_000_000) {
    return { ok: false, error: '예수금은 10만 ~ 10억 사이여야 합니다' };
  }
  return { ok: true, value: cash };
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `node --test src/lib/sim-reset-targets.test.ts`
Expected: PASS (4 tests)

- [ ] **Step 5: 커밋**

```bash
git add src/lib/sim-reset-targets.ts src/lib/sim-reset-targets.test.ts
git commit -m "feat(sim-reset): 리셋 대상 목록·상태 페이로드·검증 순수 로직"
```

---

### Task 2: Git Data API 원자 커밋 헬퍼

**Files:**
- Create: `src/lib/github-tree-commit.ts`
- Test: `src/lib/github-tree-commit.test.ts`

**Interfaces:**
- Consumes: 없음(fetch를 인자로 주입해 테스트 가능하게)
- Produces: `commitFilesAtomically(opts: { owner: string; repo: string; branch: string; message: string; files: { path: string; content: string }[]; token: string; fetchImpl?: typeof fetch }): Promise<{ commitSha: string }>` — 5단계(ref→base tree→new tree→commit→ref update)를 1커밋으로 수행. ref update 409 시 1회 재시도.

**설명:** 순수하게 테스트하기 위해 `fetchImpl`을 주입받는다(기본값 전역 fetch). 각 GitHub 호출을 스텁으로 검증한다.

- [ ] **Step 1: 실패 테스트 작성**

`src/lib/github-tree-commit.test.ts`:
```ts
import { test } from 'node:test';
import assert from 'node:assert';
import { commitFilesAtomically } from './github-tree-commit.ts';

function makeFakeFetch(log: any[]) {
  // 순서: GET ref, GET commit, POST tree, POST commit, PATCH ref
  const responses = [
    { ok: true, json: async () => ({ object: { sha: 'REFSHA' } }) },          // GET ref
    { ok: true, json: async () => ({ tree: { sha: 'BASETREE' } }) },          // GET commit
    { ok: true, json: async () => ({ sha: 'NEWTREE' }) },                     // POST tree
    { ok: true, json: async () => ({ sha: 'NEWCOMMIT' }) },                   // POST commit
    { ok: true, json: async () => ({}) },                                     // PATCH ref
  ];
  let i = 0;
  return async (url: string, init?: any) => {
    log.push({ url, method: init?.method ?? 'GET', body: init?.body });
    return responses[i++] as any;
  };
}

test('원자 커밋: ref→tree→commit→ref, tree에 파일 포함', async () => {
  const log: any[] = [];
  const res = await commitFilesAtomically({
    owner: 'o', repo: 'r', branch: 'db-data', message: 'msg', token: 'T',
    files: [{ path: 'data/a.json', content: '{}' }, { path: 'data/b.csv', content: 'h\n' }],
    fetchImpl: makeFakeFetch(log) as any,
  });
  assert.equal(res.commitSha, 'NEWCOMMIT');
  assert.equal(log.length, 5);
  assert.match(log[0].url, /git\/ref\/heads\/db-data/);
  // POST tree(3번째) body에 두 파일 경로가 담긴다
  const treeBody = JSON.parse(log[2].body);
  assert.equal(treeBody.base_tree, 'BASETREE');
  assert.deepEqual(treeBody.tree.map((t: any) => t.path), ['data/a.json', 'data/b.csv']);
  assert.equal(treeBody.tree[0].mode, '100644');
  // PATCH ref(5번째)가 새 커밋으로 이동
  assert.match(log[4].url, /git\/refs\/heads\/db-data/);
  assert.equal(JSON.parse(log[4].body).sha, 'NEWCOMMIT');
});
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `node --test src/lib/github-tree-commit.test.ts`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: 최소 구현**

`src/lib/github-tree-commit.ts`:
```ts
interface CommitOpts {
  owner: string; repo: string; branch: string; message: string;
  files: { path: string; content: string }[];
  token: string; fetchImpl?: typeof fetch;
}

export async function commitFilesAtomically(opts: CommitOpts): Promise<{ commitSha: string }> {
  const f = opts.fetchImpl ?? fetch;
  const base = `https://api.github.com/repos/${opts.owner}/${opts.repo}`;
  const headers = {
    Authorization: `token ${opts.token}`,
    Accept: 'application/vnd.github.v3+json',
    'Content-Type': 'application/json',
  };

  const doCommit = async (): Promise<string> => {
    // 1. 브랜치 ref → 최신 커밋 sha
    const refRes = await f(`${base}/git/ref/heads/${opts.branch}`, { headers, cache: 'no-store' } as any);
    if (!refRes.ok) throw new Error(`ref read ${refRes.status}`);
    const refSha = (await refRes.json()).object.sha as string;

    // 2. 커밋 → base tree sha
    const cRes = await f(`${base}/git/commits/${refSha}`, { headers, cache: 'no-store' } as any);
    if (!cRes.ok) throw new Error(`commit read ${cRes.status}`);
    const baseTree = (await cRes.json()).tree.sha as string;

    // 3. 새 tree (파일 inline content, blob 자동 생성)
    const treeRes = await f(`${base}/git/trees`, {
      method: 'POST', headers,
      body: JSON.stringify({
        base_tree: baseTree,
        tree: opts.files.map(file => ({ path: file.path, mode: '100644', type: 'blob', content: file.content })),
      }),
    } as any);
    if (!treeRes.ok) throw new Error(`tree ${treeRes.status}: ${await treeRes.text()}`);
    const newTree = (await treeRes.json()).sha as string;

    // 4. 커밋 생성
    const commitRes = await f(`${base}/git/commits`, {
      method: 'POST', headers,
      body: JSON.stringify({ message: opts.message, tree: newTree, parents: [refSha] }),
    } as any);
    if (!commitRes.ok) throw new Error(`commit create ${commitRes.status}`);
    const newCommit = (await commitRes.json()).sha as string;

    // 5. ref 이동 (fast-forward만)
    const patchRes = await f(`${base}/git/refs/heads/${opts.branch}`, {
      method: 'PATCH', headers,
      body: JSON.stringify({ sha: newCommit, force: false }),
    } as any);
    if (!patchRes.ok) {
      const err: any = new Error(`ref update ${patchRes.status}`);
      err.conflict = patchRes.status === 422 || patchRes.status === 409;
      throw err;
    }
    return newCommit;
  };

  try {
    return { commitSha: await doCommit() };
  } catch (e: any) {
    if (e?.conflict) return { commitSha: await doCommit() }; // 1회 재시도(최신 ref로)
    throw e;
  }
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `node --test src/lib/github-tree-commit.test.ts`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/lib/github-tree-commit.ts src/lib/github-tree-commit.test.ts
git commit -m "feat(sim-reset): GitHub Git Data API 단일 원자 커밋 헬퍼(주입식 fetch)"
```

---

### Task 3: 리셋 API 라우트

**Files:**
- Create: `src/app/api/simulation/reset/route.ts`

**Interfaces:**
- Consumes: `RESET_TARGETS`, `RESET_CSV_HEADER`, `buildResetState`, `validateCash` (Task 1); `commitFilesAtomically` (Task 2)
- Produces: `POST /api/simulation/reset` — body `{ cash:number }` → `{ success:true, cash, sims:string[] }` | 오류

**설명:** 이 라우트는 외부 I/O(GitHub·인증)라 단위 테스트 대신 타입체크(`next build` 계열)와 수동 검증으로 확인한다(Task 5). 순수 로직은 Task1·2에서 이미 커버됨.

- [ ] **Step 1: 라우트 구현**

`src/app/api/simulation/reset/route.ts`:
```ts
import { NextResponse } from 'next/server';
import { getToken } from 'next-auth/jwt';
import { RESET_TARGETS, RESET_CSV_HEADER, buildResetState, validateCash } from '@/lib/sim-reset-targets';
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

  const v = validateCash(body?.cash);
  if (!v.ok) return NextResponse.json({ success: false, error: v.error }, { status: 400 });

  const stateJson = JSON.stringify(buildResetState(v.value), null, 2);
  const files = RESET_TARGETS.flatMap(t => ([
    { path: `data/${t.stateFile}`, content: stateJson },
    { path: `data/${t.csvFile}`, content: RESET_CSV_HEADER },
  ]));

  try {
    await commitFilesAtomically({
      owner: OWNER, repo: REPO, branch: BRANCH, token: GITHUB_PAT,
      message: `chore(sim): reset ${RESET_TARGETS.length} simulators to ${v.value}원 (dashboard)`,
      files,
    });
  } catch (e: any) {
    return NextResponse.json({ success: false, error: `리셋 실패: ${e?.message ?? e}` }, { status: 500 });
  }

  return NextResponse.json({ success: true, cash: v.value, sims: RESET_TARGETS.map(t => t.id) });
}
```

- [ ] **Step 2: 타입/빌드 확인**

Run: `npx next lint --file src/app/api/simulation/reset/route.ts` (통과) 그리고 `npm run build`가 이 라우트를 타입에러 없이 컴파일하는지 확인(장시간이면 최소 타입체크만).
Expected: 타입 에러 없음.

- [ ] **Step 3: 커밋**

```bash
git add src/app/api/simulation/reset/route.ts
git commit -m "feat(sim-reset): POST /api/simulation/reset (세션 인증 + 원자 커밋)"
```

---

### Task 4: 대시보드 UI (예수금 입력·리셋 버튼·확인 모달)

**Files:**
- Modify: `src/app/trade/TradeClient.tsx`

**Interfaces:**
- Consumes: `POST /api/simulation/reset` (Task 3)
- Produces: 없음(최종 UI)

**설명:** 기존 state/모달/알림 패턴(`notification`, `useState`)을 그대로 따른다. 심 경쟁 카드 영역 근처에 리셋 블록을 추가한다. 정확한 삽입 위치는 구현 시 `simConfigs` 렌더링 블록 바로 위/아래에서 결정한다.

- [ ] **Step 1: 리셋 상태 추가**

`src/app/trade/TradeClient.tsx`의 다른 `useState` 선언부(예: 86~99행 program 상태 근처)에 추가:
```tsx
const [resetCash, setResetCash] = useState<number | ''>(3000000);
const [resetConfirmOpen, setResetConfirmOpen] = useState(false);
const [resetBusy, setResetBusy] = useState(false);
```

- [ ] **Step 2: 리셋 핸들러 추가**

컴포넌트 내 함수 영역(다른 핸들러 근처)에 추가:
```tsx
const handleReset = async () => {
  if (typeof resetCash !== 'number' || !Number.isInteger(resetCash) || resetCash < 100000 || resetCash > 1000000000) {
    setNotification({ title: '리셋 불가', msg: '예수금은 10만 ~ 10억 사이 정수여야 합니다.', color: 'red' });
    setResetConfirmOpen(false);
    return;
  }
  setResetBusy(true);
  try {
    const res = await fetch('/api/simulation/reset', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cash: resetCash }),
    });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.error || `HTTP ${res.status}`);
    setNotification({ title: '리셋 완료', msg: `${data.sims.length}개 시뮬레이터를 ${resetCash.toLocaleString()}원으로 초기화했습니다. 대시보드 반영까지 잠시 걸릴 수 있습니다.`, color: 'green' });
  } catch (e: any) {
    setNotification({ title: '리셋 실패', msg: e?.message ?? String(e), color: 'red' });
  } finally {
    setResetBusy(false);
    setResetConfirmOpen(false);
  }
};
```

- [ ] **Step 3: 리셋 UI 블록 추가(심 경쟁 카드 영역 근처)**

`simConfigs`(또는 심 통계 카드)를 렌더링하는 JSX 블록 근처에 삽입:
```tsx
<div style={{ margin: '16px 0', padding: '12px', border: '1px solid #eee', borderRadius: 8 }}>
  <div style={{ fontWeight: 600, marginBottom: 8 }}>시뮬레이터 리셋</div>
  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
    <input
      type="number"
      value={resetCash}
      onChange={e => setResetCash(e.target.value === '' ? '' : Number(e.target.value))}
      placeholder="예수금(원)"
      style={{ width: 160, padding: '6px 8px' }}
    />
    <button onClick={() => setResetConfirmOpen(true)} disabled={resetBusy}
      style={{ padding: '6px 14px', background: '#c92a2a', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}>
      {resetBusy ? '리셋 중…' : '전체 리셋'}
    </button>
  </div>
</div>

{resetConfirmOpen && (
  <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
    <div style={{ background: '#fff', padding: 24, borderRadius: 10, maxWidth: 420 }}>
      <div style={{ fontWeight: 700, marginBottom: 10 }}>정말 초기화할까요?</div>
      <div style={{ marginBottom: 16, lineHeight: 1.5 }}>
        9개 시뮬레이터(Sim1~7, Sim10)를 <b>{typeof resetCash === 'number' ? resetCash.toLocaleString() : '-'}원</b>으로 초기화하고
        모든 거래기록을 삭제합니다. <b>되돌릴 수 없습니다.</b>
      </div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button onClick={() => setResetConfirmOpen(false)} disabled={resetBusy}
          style={{ padding: '6px 14px' }}>취소</button>
        <button onClick={handleReset} disabled={resetBusy}
          style={{ padding: '6px 14px', background: '#c92a2a', color: '#fff', border: 'none', borderRadius: 6 }}>
          {resetBusy ? '리셋 중…' : '초기화'}
        </button>
      </div>
    </div>
  </div>
)}
```

- [ ] **Step 4: 빌드/타입 확인**

Run: `npm run build` (또는 최소 `npx tsc --noEmit`가 설정돼 있으면 그것). 이 파일에 타입 에러가 없는지 확인.
Expected: 타입 에러 없음.

- [ ] **Step 5: 커밋**

```bash
git add src/app/trade/TradeClient.tsx
git commit -m "feat(sim-reset): 대시보드 예수금 입력·리셋 버튼·확인 모달"
```

---

### Task 5: 수동 통합 검증

**Files:** 없음(런타임 검증)

- [ ] **Step 1: 로컬 실행**

Run: `npm run dev` → 브라우저에서 `/trade` 접속(로그인 필요).

- [ ] **Step 2: 미인증 401 확인**

로그아웃 상태에서 `POST /api/simulation/reset`를 curl로 호출 → 401 확인:
```bash
curl -i -X POST http://localhost:3000/api/simulation/reset -H 'Content-Type: application/json' -d '{"cash":3000000}'
```
Expected: HTTP 401.

- [ ] **Step 3: 검증 실패 400 확인**

로그인 세션 쿠키로 `{"cash":50000}`(하한 미만) 호출 → 400.

- [ ] **Step 4: 정상 리셋**

대시보드에서 예수금 3,000,000 입력 → 전체 리셋 → 초기화 확인 모달 → 초기화.
- GitHub `db-data` 브랜치에 커밋 1건 생성 확인(9 상태 JSON = cash 3,000,000·portfolio {}, 9 CSV = 헤더만).
- 대시보드 stats가 (CDN 반영 후) 모든 심 3,000,000원·수익률 0%로 표시되는지 확인.

- [ ] **Step 5: 마무리 커밋(필요 시)**

검증 중 수정이 있었으면 커밋. 없으면 스킵.

---

## 알려진 한계 (설계문서 §6과 동일)
- 스크래퍼 런 중 리셋 시 그 런 커밋이 리셋을 덮어쓸 수 있음(작은 창) — 런 사이 리셋 권장. [[db-data-verification-gotchas]]
- 리셋 후 stats(raw.github CDN) 반영 지연 가능.
