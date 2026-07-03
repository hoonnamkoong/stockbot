# 프로그램 매매 수익률/평가손익 표시 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실전 계좌 카드에 "프로그램 매매 수익률(%)"과 "프로그램 매매 평가손익(원)"을 기존 예수금/총자산수익률/총평가손익과 별도로 표시하고, 프로그램 예산이 나중에 추가/변경되어도 코드 수정 없이 자동 반영되게 한다.

**Architecture:** `program_positions.json`(비공개 stockbot-secret repo)의 `positions`/`realized_pnl`을 GET `/api/trade/program`에 추가로 실어 보낸다. 프론트는 이미 30초마다 폴링 중인 실시간 시세(`balance.holdings`)와 이 포지션을 code로 매칭해 미실현손익을 계산하고, `realized_pnl + unrealized_pnl`을 현재 설정된 budget으로 나눠 수익률을 렌더 시점마다 인라인으로 도출한다.

**Tech Stack:** Next.js API route(TypeScript, GitHub Contents API), React(TypeScript, Mantine UI) — 기존 코드베이스 그대로, 신규 의존성 없음.

## Global Constraints

- 기존 예수금/총자산수익률/총평가손익 표시는 절대 변경하지 않는다 (스펙: `docs/superpowers/specs/2026-07-03-program-trading-pnl-display-design.md`).
- 프로그램 매매 수익률 분모는 현재 confirmed `budget`(설정 예산) 기준. budget이 바뀌면 그 시점부터 새 기준으로 계산(과거 소급 재계산 없음).
- 표시 조건: `budget>0 || positions 존재 || realized_pnl≠0` 일 때만 렌더링, 세 조건 모두 거짓이면 항목 자체를 렌더링하지 않는다.
- `program_positions.json` 조회 실패/404는 fail-safe로 `{positions:{}, realized_pnl:0}`으로 대체하고, 기존 GET 응답(enabled/selected_sim/budget/sims)의 성공을 절대 막지 않는다.
- `program_trader.py`(매매 실행 로직)는 변경하지 않는다 — 순수 표시 기능.
- 이 저장소에는 jest/vitest 등 테스트 러너가 없다(package.json 확인 완료). 검증은 `npx tsc --noEmit`(타입 체크) + `npm run build`(컴파일) + 브라우저 수동 확인으로 한다.

---

### Task 1: 백엔드 — GET /api/trade/program에 프로그램 원장 노출

**Files:**
- Modify: `src/app/api/trade/program/route.ts:36-48` (getPositions 함수 추가), `:113-134` (GET 핸들러 응답 확장)

**Interfaces:**
- Consumes: 기존 `OWNER`, `SECRET_REPO`, `SECRET_BRANCH`, `GITHUB_PAT` 상수 (파일 상단 17-21행에 이미 정의됨), `getConfig()`/`putConfig()` 패턴(38-47행).
- Produces: `getPositions(): Promise<{ positions: Record<string, { name: string; quantity: number; avg_price: number }>; realized_pnl: number }>` — Task 2(프론트엔드)가 GET 응답의 `positions`, `realized_pnl` 필드로 소비.

- [ ] **Step 1: `getPositions()` 함수 추가**

`src/app/api/trade/program/route.ts`에서 `putConfig` 함수 정의(38-47행) 바로 뒤, PIN 무차별 대입 방어 주석(49행) 바로 앞에 삽입한다.

기존 코드(38-49행, 그대로 유지):
```typescript
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
```

이 사이에 삽입할 새 코드:
```typescript
// ── 프로그램 매매 원장(program_positions.json) 읽기 전용 조회 ────────────
// 표시 전용 데이터이므로 실패해도 GET 전체를 막지 않고 빈 원장으로 대체한다(fail-safe).
const POSITIONS_PATH = 'program_positions.json';

async function getPositions(): Promise<{
    positions: Record<string, { name: string; quantity: number; avg_price: number }>;
    realized_pnl: number;
}> {
    try {
        const url = `https://api.github.com/repos/${OWNER}/${SECRET_REPO}/contents/${POSITIONS_PATH}?ref=${SECRET_BRANCH}`;
        const res = await fetch(url, {
            headers: { Authorization: `token ${GITHUB_PAT}`, Accept: 'application/vnd.github.v3+json' },
            cache: 'no-store',
        });
        if (!res.ok) return { positions: {}, realized_pnl: 0 }; // 404(미실행) 등은 빈 원장으로 취급
        const data = await res.json();
        const content = JSON.parse(Buffer.from(data.content, 'base64').toString('utf-8'));
        return {
            positions: content.positions && typeof content.positions === 'object' ? content.positions : {},
            realized_pnl: Number(content.realized_pnl) || 0,
        };
    } catch {
        return { positions: {}, realized_pnl: 0 }; // 네트워크 실패 등도 non-blocking
    }
}
```

- [ ] **Step 2: GET 핸들러 응답에 `positions`, `realized_pnl` 추가**

기존 코드(113-134행):
```typescript
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
```

새 코드로 교체:
```typescript
export async function GET(request: Request) {
    try {
        const token = await getToken({ req: request as any, secret: process.env.NEXTAUTH_SECRET });
        if (!token) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

        const { content } = await getConfig();
        const sims = await fetchTradeableSims();
        const validIds = new Set(sims.map((s) => s.id));
        // selected_sim이 현재 매매 가능 목록에 없으면 무효(파이프라인도 OFF 취급)
        const selectedValid = !!content.selected_sim && validIds.has(content.selected_sim);
        const { positions, realized_pnl } = await getPositions();
        return NextResponse.json({
            enabled: !!content.enabled,
            selected_sim: content.selected_sim ?? null,
            budget: Number(content.budget) || 0,
            selected_valid: selectedValid,
            updated_at: content.updated_at ?? null,
            sims, // 프론트 드롭다운 재사용
            positions, // 프로그램 원장 포지션(code -> {name, quantity, avg_price})
            realized_pnl, // 프로그램 누적 실현손익(원)
        });
    } catch (error: any) {
        return NextResponse.json({ error: error.message }, { status: 500 });
    }
}
```

- [ ] **Step 3: 타입 체크**

Run: `npx tsc --noEmit`
Expected: 에러 없음(0 errors). `route.ts` 관련 에러가 나오면 타입 불일치를 수정한다.

- [ ] **Step 4: 빌드로 컴파일 확인**

Run: `npm run build`
Expected: 빌드 성공, `src/app/api/trade/program/route.ts` 관련 컴파일 에러 없음.

- [ ] **Step 5: 로컬 dev 서버에서 응답 형태 수동 확인**

Run: `npm run dev` (백그라운드 실행 후) → 브라우저에서 `/login`으로 로그인 → `/trade` 접속 → 개발자 도구 Network 탭에서 `GET /api/trade/program` 요청의 응답 JSON을 확인.
Expected: 응답에 `positions`(object, 로컬 secret repo 접근 실패 시 `{}`)와 `realized_pnl`(number, 실패 시 `0`) 필드가 존재하고, 기존 `enabled/selected_sim/budget/sims` 필드는 그대로 있으며 요청이 500으로 실패하지 않는다.

- [ ] **Step 6: 커밋**

```bash
git add src/app/api/trade/program/route.ts
git commit -m "feat(trade): 프로그램 매매 원장(positions/realized_pnl) API 노출"
```

---

### Task 2: 프론트엔드 — 프로그램 매매 수익률/평가손익 표시

**Files:**
- Modify: `src/app/trade/TradeClient.tsx:84-92` (state 추가), `:202-212` (fetchProgram 파싱 추가), `:509-579` (renderRealPortfolioSection 계산 + UI 블록 추가)

**Interfaces:**
- Consumes: Task 1이 만든 GET `/api/trade/program` 응답의 `positions: Record<string, {name, quantity, avg_price}>`, `realized_pnl: number` 필드. 기존 `balance.holdings`(이미 폴링 중, 각 항목에 `code`, `price` 존재 — `src/app/trade/TradeClient.tsx:26-42` `Holding`/`BalanceData` 인터페이스 참고).
- Produces: 없음(최종 UI 렌더링, 이후 태스크 없음).

- [ ] **Step 1: state 추가**

기존 코드(`src/app/trade/TradeClient.tsx:84-92`):
```typescript
    // Program trading (실전 계좌 자동 심 운용)
    const [programEnabled, setProgramEnabled] = useState(false);
    const [programSim, setProgramSim] = useState<string | null>(null);
    const [programBudget, setProgramBudget] = useState<number | ''>('');
    const [programSims, setProgramSims] = useState<{ id: string; name: string; description: string }[]>([]);
    const [programValid, setProgramValid] = useState(true);
    const [programBusy, setProgramBusy] = useState(false);
    const [programPinOpen, setProgramPinOpen] = useState(false);
    const [programPin, setProgramPin] = useState('');
```

새 코드로 교체(끝에 두 줄 추가):
```typescript
    // Program trading (실전 계좌 자동 심 운용)
    const [programEnabled, setProgramEnabled] = useState(false);
    const [programSim, setProgramSim] = useState<string | null>(null);
    const [programBudget, setProgramBudget] = useState<number | ''>('');
    const [programSims, setProgramSims] = useState<{ id: string; name: string; description: string }[]>([]);
    const [programValid, setProgramValid] = useState(true);
    const [programBusy, setProgramBusy] = useState(false);
    const [programPinOpen, setProgramPinOpen] = useState(false);
    const [programPin, setProgramPin] = useState('');
    const [programPositions, setProgramPositions] = useState<Record<string, { name: string; quantity: number; avg_price: number }>>({});
    const [programRealizedPnl, setProgramRealizedPnl] = useState(0);
```

- [ ] **Step 2: `fetchProgram`에서 새 필드 파싱**

기존 코드(`src/app/trade/TradeClient.tsx:202-212`):
```typescript
    const fetchProgram = useCallback(async () => {
        try {
            const res = await axios.get('/api/trade/program');
            const d = res.data || {};
            setProgramEnabled(!!d.enabled);
            setProgramSim(d.selected_sim ?? null);
            setProgramBudget(d.budget ? Number(d.budget) : '');
            setProgramSims(Array.isArray(d.sims) ? d.sims : []);
            setProgramValid(d.selected_valid !== false);
        } catch { /* 미로그인/네트워크 실패 시 조용히 무시 */ }
    }, []);
```

새 코드로 교체:
```typescript
    const fetchProgram = useCallback(async () => {
        try {
            const res = await axios.get('/api/trade/program');
            const d = res.data || {};
            setProgramEnabled(!!d.enabled);
            setProgramSim(d.selected_sim ?? null);
            setProgramBudget(d.budget ? Number(d.budget) : '');
            setProgramSims(Array.isArray(d.sims) ? d.sims : []);
            setProgramValid(d.selected_valid !== false);
            setProgramPositions(d.positions && typeof d.positions === 'object' ? d.positions : {});
            setProgramRealizedPnl(Number(d.realized_pnl) || 0);
        } catch { /* 미로그인/네트워크 실패 시 조용히 무시 */ }
    }, []);
```

- [ ] **Step 3: 계산 로직 추가 (renderRealPortfolioSection 상단)**

기존 코드(`src/app/trade/TradeClient.tsx:509-515`):
```typescript
    function renderRealPortfolioSection() {
        const deposit = balance?.deposit ?? 0;
        // [V8.9.9 Hotfix] 매도 완료되어 잔고가 0주인 종목은 포트폴리오(UI)에서 제외 필터링
        const holdings = (balance?.holdings || []).filter((h: any) => Number(h.qty || h.quantity || 0) > 0);
        const totalEval = holdings.reduce((sum: any, h: any) => sum + ((h.price || 0) * (h.qty || 0)), 0);
        const totalPL = holdings.reduce((sum: any, h: any) => sum + (h.pl_amount || 0), 0);

        return (
```

새 코드로 교체:
```typescript
    function renderRealPortfolioSection() {
        const deposit = balance?.deposit ?? 0;
        // [V8.9.9 Hotfix] 매도 완료되어 잔고가 0주인 종목은 포트폴리오(UI)에서 제외 필터링
        const holdings = (balance?.holdings || []).filter((h: any) => Number(h.qty || h.quantity || 0) > 0);
        const totalEval = holdings.reduce((sum: any, h: any) => sum + ((h.price || 0) * (h.qty || 0)), 0);
        const totalPL = holdings.reduce((sum: any, h: any) => sum + (h.pl_amount || 0), 0);

        // 프로그램 매매 수익률/평가손익: 자체 원장(avg_price) 기준 + 실시간 시세 매칭
        // (브로커 계좌 전체 손익과 섞이지 않도록 program_positions.json의 avg_price를 그대로 씀)
        const allHoldings = balance?.holdings || [];
        const programUnrealizedPnl = Object.entries(programPositions).reduce((sum, [code, pos]) => {
            const live = allHoldings.find((h: any) => h.code === code);
            const currentPrice = live?.price ?? pos.avg_price; // 시세 매칭 실패 시 기여분 0
            return sum + (currentPrice - pos.avg_price) * pos.quantity;
        }, 0);
        const programTotalPnl = programRealizedPnl + programUnrealizedPnl;
        const programBudgetNum = Number(programBudget) || 0;
        const programTotalPnlRate = programBudgetNum > 0 ? (programTotalPnl / programBudgetNum) * 100 : 0;
        const programHasData = programBudgetNum > 0 || Object.keys(programPositions).length > 0 || programRealizedPnl !== 0;

        return (
```

- [ ] **Step 4: 조건부 UI 블록 추가**

기존 코드(`src/app/trade/TradeClient.tsx:561-579`):
```typescript
                    <Group grow mb="md" align="flex-end">
                        <Stack gap={2}>
                            <Text size="xs" c="dimmed">예수금 (잔고)</Text>
                            <Text fw={700} size="lg">{(Number(deposit) || 0).toLocaleString()} 원</Text>
                        </Stack>
                        <Stack gap={2}>
                            <Text size="xs" c="dimmed">총 자산수익률</Text>
                            <Text fw={800} size="lg" c={totalPL >= 0 ? 'red' : 'blue'}>
                                {totalPL >= 0 ? '+' : ''}{(totalEval > 0 ? (totalPL / (totalEval - totalPL)) * 100 : 0).toFixed(2)}%
                            </Text>
                        </Stack>
                        <Stack gap={2}>
                            <Text size="xs" c="dimmed">총 평가손익</Text>
                            <Text fw={700} size="lg" c={totalPL >= 0 ? 'red' : 'blue'}>
                                {totalPL >= 0 ? '+' : ''}{(Number(totalPL) || 0).toLocaleString()} 원
                            </Text>
                        </Stack>
                    </Group>
                    <Divider mb="xs" label="보유 포트폴리오 (일괄 매도 가능)" labelPosition="center" />
```

새 코드로 교체(기존 `Group` 내용은 그대로 두고, 그 뒤 `Divider` 앞에 새 조건부 `Group`을 삽입):
```typescript
                    <Group grow mb="md" align="flex-end">
                        <Stack gap={2}>
                            <Text size="xs" c="dimmed">예수금 (잔고)</Text>
                            <Text fw={700} size="lg">{(Number(deposit) || 0).toLocaleString()} 원</Text>
                        </Stack>
                        <Stack gap={2}>
                            <Text size="xs" c="dimmed">총 자산수익률</Text>
                            <Text fw={800} size="lg" c={totalPL >= 0 ? 'red' : 'blue'}>
                                {totalPL >= 0 ? '+' : ''}{(totalEval > 0 ? (totalPL / (totalEval - totalPL)) * 100 : 0).toFixed(2)}%
                            </Text>
                        </Stack>
                        <Stack gap={2}>
                            <Text size="xs" c="dimmed">총 평가손익</Text>
                            <Text fw={700} size="lg" c={totalPL >= 0 ? 'red' : 'blue'}>
                                {totalPL >= 0 ? '+' : ''}{(Number(totalPL) || 0).toLocaleString()} 원
                            </Text>
                        </Stack>
                    </Group>
                    {programHasData && (
                        <Group grow mb="md" align="flex-end">
                            <Stack gap={2}>
                                <Text size="xs" c="dimmed">프로그램 매매 수익률</Text>
                                <Text fw={800} size="lg" c={programTotalPnl >= 0 ? 'red' : 'blue'}>
                                    {programTotalPnl >= 0 ? '+' : ''}{programTotalPnlRate.toFixed(2)}%
                                </Text>
                            </Stack>
                            <Stack gap={2}>
                                <Text size="xs" c="dimmed">프로그램 매매 평가손익</Text>
                                <Text fw={700} size="lg" c={programTotalPnl >= 0 ? 'red' : 'blue'}>
                                    {programTotalPnl >= 0 ? '+' : ''}{Math.round(programTotalPnl).toLocaleString()} 원
                                </Text>
                            </Stack>
                        </Group>
                    )}
                    <Divider mb="xs" label="보유 포트폴리오 (일괄 매도 가능)" labelPosition="center" />
```

- [ ] **Step 5: 타입 체크**

Run: `npx tsc --noEmit`
Expected: 에러 없음.

- [ ] **Step 6: 빌드 확인**

Run: `npm run build`
Expected: 빌드 성공.

- [ ] **Step 7: 브라우저 수동 확인 — 빈 상태(숨김) 확인**

Run: `npm run dev` → 브라우저에서 로그인 후 `/trade` 접속.
Expected: 로컬 환경은 secret repo 접근이 없거나(또는 프로그램 매매를 설정한 적 없는 계정 상태라면) `programHasData`가 false가 되어 "프로그램 매매 수익률/평가손익" 블록이 전혀 보이지 않고, 기존 예수금/총자산수익률/총평가손익 3칸은 이전과 동일하게 보인다.

- [ ] **Step 8: 브라우저 수동 확인 — 표시 상태 확인**

`/trade` 페이지에서 "프로그램 예산(원)" 입력란에 임의의 값(예: 1000000)을 입력만 하고(ON 켜지 않아도 `programBudget` state는 즉시 반영됨) 화면을 확인.
Expected: "프로그램 매매 수익률"과 "프로그램 매매 평가손익" 블록이 즉시 나타난다(포지션/실현손익이 0이면 `+0.00%` / `+0 원`으로 표시). 입력값을 지우면(0으로) 다시 사라진다(단, 이미 서버에 저장된 positions/realized_pnl이 있는 계정이라면 예산을 지워도 계속 보이는 것이 정상 — Global Constraints의 표시 조건 참고).

- [ ] **Step 9: 커밋**

```bash
git add src/app/trade/TradeClient.tsx
git commit -m "feat(trade): 프로그램 매매 수익률/평가손익 별도 표시"
```

---

## Self-Review Notes

- **스펙 커버리지:** "기존 3항목 유지"(Task 2 Step 4, 기존 Group 불변), "프로그램 매매 수익률/평가손익 별도 표시"(Task 2 Step 4 신규 Group), "예산 변경 시 자동 반영"(Task 2 Step 3, `programBudget`/`programPositions`/`programRealizedPnl` state 기반 매 렌더 재계산 — 별도 캐싱 없음), "빈 상태 숨김"(Task 2 Step 3 `programHasData` + Step 4 조건부 렌더), "원장 조회 실패 시 GET 응답 안 막힘"(Task 1 Step 1 try/catch fail-safe) 모두 태스크로 커버됨.
- **타입 일관성:** `positions` 타입은 Task 1(`Record<string, { name: string; quantity: number; avg_price: number }>`)과 Task 2 state 선언이 동일한 시그니처로 일치함.
- **플레이스홀더:** 없음 — 모든 스텝에 실제 코드/명령어 포함.
