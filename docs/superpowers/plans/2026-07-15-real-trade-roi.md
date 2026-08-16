# 실거래 매매 히스토리 ROI 계산 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실거래 매도 건마다 KIS 실현손익 API로 계산한 ROI(%)와 ROI(금액)를 매매 히스토리에 표시한다.

**Architecture:** `getRealTradeHistory`가 기존 일별체결(ccld) API에 더해 KIS 기간별매매손익(TTTC8715R)을 함께 호출한다. 순수 함수 `matchRealizedRoi`가 두 결과를 `종목코드+일자` 기준 FIFO로 조인해 각 SELL 체결 행에 `roi`·`roiAmount`를 붙인다. 프론트는 real 히스토리 테이블에 ROI(금액) 열을 추가하고 BUY(`-`)/매칭실패 SELL("측정 불가")/성공 SELL(값)을 구분해 렌더한다.

**Tech Stack:** TypeScript, Next.js(App Router), axios, Mantine(Table/Badge/Text). JS/TS 테스트 러너 없음 → 순수 로직은 scratch 검증 스크립트, 통합은 `npm run build` + 실호출 로그 + 브라우저 육안 검증.

## Global Constraints

- 금융 수치 정직성: 조회 실패/원가 미확보를 0·가짜값으로 채우지 않는다. 값이 없으면 SELL은 "측정 불가", BUY는 `-`. (spec [[no-fabricated-financial-values]])
- 대상은 실거래(real)만. 시뮬레이터 히스토리(`type !== 'real'`) 로직·표시 변경 금지.
- 기존 코드 스타일 유지(주변 코드와 동일 컨벤션). 무관한 리팩터링 금지.
- KIS 실호출 헤더/파라미터/응답 필드명은 첫 실호출 로그로 실제 키를 확인해 확정한다(spec의 "주의" 항목).
- 커밋은 사용자가 요청할 때만 수행. 각 Task의 "Commit" 스텝은 사용자 승인 후 실행.

---

## File Structure

- `src/lib/kis-api.ts` (Modify)
  - 신규 export 순수 함수 `matchRealizedRoi(fills, buckets)` — 조인/FIFO 로직.
  - 신규 async `getRealizedProfitBuckets(from, to)` — TTTC8715R 호출 → 버킷 Map.
  - `getRealTradeHistory` 수정 — 두 API 호출 후 `matchRealizedRoi` 적용.
- `src/app/trade/TradeClient.tsx` (Modify)
  - `renderHistoryTable`의 real 분기에 ROI(금액) 열 추가 + 렌더 분기.
- `scratch/verify_roi_match.mjs` (Create, 커밋 안 함) — 순수 함수 검증 스크립트.

---

## Task 1: 조인/FIFO 순수 함수 `matchRealizedRoi`

**Files:**
- Modify: `src/lib/kis-api.ts` (신규 export 함수 추가 — `getRealTradeHistory` 위쪽, export 섹션)
- Verify: `scratch/verify_roi_match.mjs` (Create, 커밋 안 함)

**Interfaces:**
- Produces:
  - `type RealFill = { action: 'BUY' | 'SELL'; code: string; time: string; qty: string | number; roi?: string; roiAmount?: number; [k: string]: any }`
  - `type ProfitEntry = { sellQty: number; roiPct: string; roiAmount: number }` (roiPct는 부호 포함 문자열, 예 `"+3.20"` / `"-1.50"`)
  - `export function matchRealizedRoi(fills: RealFill[], buckets: Map<string, ProfitEntry[]>): RealFill[]`
    - 버킷 키: `` `${code}_${yyyymmdd}` `` (yyyymmdd는 fill.time의 날짜부 `-` 제거).
    - **입력 fills를 변형하지 않고** 새 배열을 반환(각 원소는 얕은 복사 후 필드 추가).
    - 처리는 **fill 배열 순서대로**(호출부에서 최신→과거로 들어와도, 소진은 버킷별 remaining을 순차 사용).
    - BUY 행: 그대로 통과(roi/roiAmount 미부여).
    - SELL 행: 해당 버킷에서 `fillQty`만큼 FIFO 소진:
      - 남은 엔트리 합계 수량이 `fillQty` 이상이면:
        `roiAmount` = 소진분들의 pnl 비례합(엔트리별 `roiAmount * consumed/entry.sellQty` 합, 반올림),
        `roi` = 소진분들의 qty-가중 평균 손익률을 부호 포함 소수1자리 문자열로(1:1이면 엔트리 값 그대로).
        소진한 만큼 엔트리 `sellQty` 차감(0 되면 다음 엔트리로).
      - 버킷이 없거나 남은 수량이 `fillQty` 미만이면: roi/roiAmount 미부여(측정 불가).

- [ ] **Step 1: 순수 함수 구현**

`src/lib/kis-api.ts`의 `getRealTradeHistory` 함수 정의 바로 위에 아래를 추가한다.

```typescript
// --- Realized ROI 조인 (일별체결 SELL 행 ↔ 기간별매매손익 버킷) ---
export type RealFill = {
    action: 'BUY' | 'SELL';
    code: string;
    time: string;
    qty: string | number;
    roi?: string;
    roiAmount?: number;
    [k: string]: any;
};

export type ProfitEntry = { sellQty: number; roiPct: string; roiAmount: number };

/**
 * 각 SELL 체결 행에 실현손익(roi %, roiAmount 원)을 FIFO로 매칭한다.
 * 원가를 확보 못 한 SELL은 값을 붙이지 않는다(측정 불가). BUY는 그대로 통과.
 */
export function matchRealizedRoi(
    fills: RealFill[],
    buckets: Map<string, ProfitEntry[]>,
): RealFill[] {
    // 소진 상태를 훼손하지 않도록 버킷을 얕게 복제
    const remaining = new Map<string, ProfitEntry[]>();
    for (const [k, v] of buckets) remaining.set(k, v.map(e => ({ ...e })));

    const signedRate = (r: number): string =>
        (r >= 0 ? '+' : '') + r.toFixed(1);

    return fills.map((f) => {
        const out: RealFill = { ...f };
        if (f.action !== 'SELL') return out;

        const yyyymmdd = String(f.time).slice(0, 10).replace(/-/g, '');
        const key = `${f.code}_${yyyymmdd}`;
        const entries = remaining.get(key);
        let need = Number(f.qty) || 0;
        if (!entries || need <= 0) return out;

        const available = entries.reduce((s, e) => s + e.sellQty, 0);
        if (available < need) return out; // 원가 부족 → 측정 불가

        let pnlSum = 0;
        let rateWeighted = 0;
        const totalQty = need;
        for (const e of entries) {
            if (need <= 0) break;
            if (e.sellQty <= 0) continue;
            const take = Math.min(need, e.sellQty);
            pnlSum += Math.round(e.roiAmount * (take / e.sellQty));
            rateWeighted += (parseFloat(e.roiPct) || 0) * (take / totalQty);
            e.sellQty -= take;
            need -= take;
        }
        out.roiAmount = pnlSum;
        out.roi = signedRate(rateWeighted);
        return out;
    });
}
```

- [ ] **Step 2: 검증 스크립트 작성**

`scratch/verify_roi_match.mjs`를 만든다(함수 로직을 그대로 복제해 순수 검증 — 이 파일은 커밋하지 않음).

```javascript
// matchRealizedRoi 로직 복제본 (검증 전용)
function matchRealizedRoi(fills, buckets) {
    const remaining = new Map();
    for (const [k, v] of buckets) remaining.set(k, v.map(e => ({ ...e })));
    const signedRate = (r) => (r >= 0 ? '+' : '') + r.toFixed(1);
    return fills.map((f) => {
        const out = { ...f };
        if (f.action !== 'SELL') return out;
        const yyyymmdd = String(f.time).slice(0, 10).replace(/-/g, '');
        const key = `${f.code}_${yyyymmdd}`;
        const entries = remaining.get(key);
        let need = Number(f.qty) || 0;
        if (!entries || need <= 0) return out;
        const available = entries.reduce((s, e) => s + e.sellQty, 0);
        if (available < need) return out;
        let pnlSum = 0, rateWeighted = 0; const totalQty = need;
        for (const e of entries) {
            if (need <= 0) break;
            if (e.sellQty <= 0) continue;
            const take = Math.min(need, e.sellQty);
            pnlSum += Math.round(e.roiAmount * (take / e.sellQty));
            rateWeighted += (parseFloat(e.roiPct) || 0) * (take / totalQty);
            e.sellQty -= take; need -= take;
        }
        out.roiAmount = pnlSum; out.roi = signedRate(rateWeighted);
        return out;
    });
}

let pass = 0, fail = 0;
const check = (name, cond) => { if (cond) { pass++; } else { fail++; console.error('FAIL:', name); } };

// 1) 1:1 매칭 SELL
let r = matchRealizedRoi(
    [{ action: 'SELL', code: '005930', time: '2026-07-14 10:00:00', qty: 10 }],
    new Map([['005930_20260714', [{ sellQty: 10, roiPct: '+3.2', roiAmount: 12400 }]]]),
);
check('1:1 roiAmount', r[0].roiAmount === 12400);
check('1:1 roi', r[0].roi === '+3.2');

// 2) BUY 행은 통과(값 없음)
r = matchRealizedRoi(
    [{ action: 'BUY', code: '005930', time: '2026-07-14 09:00:00', qty: 10 }],
    new Map([['005930_20260714', [{ sellQty: 10, roiPct: '+3.2', roiAmount: 12400 }]]]),
);
check('BUY no roi', r[0].roi === undefined && r[0].roiAmount === undefined);

// 3) 버킷 없음 → 측정 불가
r = matchRealizedRoi(
    [{ action: 'SELL', code: '000660', time: '2026-07-14 10:00:00', qty: 5 }],
    new Map(),
);
check('no bucket -> undefined', r[0].roi === undefined && r[0].roiAmount === undefined);

// 4) 수량 부족(원가창 밖) → 측정 불가
r = matchRealizedRoi(
    [{ action: 'SELL', code: '005930', time: '2026-07-14 10:00:00', qty: 20 }],
    new Map([['005930_20260714', [{ sellQty: 10, roiPct: '+3.2', roiAmount: 12400 }]]]),
);
check('insufficient -> undefined', r[0].roi === undefined && r[0].roiAmount === undefined);

// 5) 같은 종목·같은 날 복수 매도 FIFO 분할
r = matchRealizedRoi(
    [
        { action: 'SELL', code: '005930', time: '2026-07-14 10:00:00', qty: 6 },
        { action: 'SELL', code: '005930', time: '2026-07-14 11:00:00', qty: 4 },
    ],
    new Map([['005930_20260714', [{ sellQty: 6, roiPct: '+3.0', roiAmount: 6000 }, { sellQty: 4, roiPct: '-1.0', roiAmount: -2000 }]]]),
);
check('split-1 amount', r[0].roiAmount === 6000);
check('split-1 rate', r[0].roi === '+3.0');
check('split-2 amount', r[1].roiAmount === -2000);
check('split-2 rate', r[1].roi === '-1.0');

// 6) 음수 손익 부호
r = matchRealizedRoi(
    [{ action: 'SELL', code: '035720', time: '2026-07-14 13:00:00', qty: 3 }],
    new Map([['035720_20260714', [{ sellQty: 3, roiPct: '-2.5', roiAmount: -4500 }]]]),
);
check('neg amount', r[0].roiAmount === -4500);
check('neg rate', r[0].roi === '-2.5');

console.log(`PASS=${pass} FAIL=${fail}`);
process.exit(fail === 0 ? 0 : 1);
```

- [ ] **Step 3: 검증 실행**

Run: `node scratch/verify_roi_match.mjs`
Expected: `PASS=10 FAIL=0` (종료코드 0)

- [ ] **Step 4: 타입체크(빌드)로 함수 컴파일 확인**

Run: `npm run build`
Expected: 빌드 성공(타입 에러 없음). (이 시점엔 `matchRealizedRoi`가 아직 호출되지 않아도 export만으로 컴파일 OK)

- [ ] **Step 5: Commit (사용자 승인 후)**

```bash
git add src/lib/kis-api.ts
git commit -m "feat(trade): 실현손익 조인 순수함수 matchRealizedRoi 추가"
```

---

## Task 2: KIS 실현손익 호출 + `getRealTradeHistory` 연결

**Files:**
- Modify: `src/lib/kis-api.ts` (신규 `getRealizedProfitBuckets`, `getRealTradeHistory` 반환부 수정)

**Interfaces:**
- Consumes: Task 1의 `matchRealizedRoi`, `ProfitEntry`. 기존 `getKISConfig`, `getAccessToken`.
- Produces:
  - `async function getRealizedProfitBuckets(fromDateStr: string, toDateStr: string): Promise<Map<string, ProfitEntry[]>>`
    - 키 `` `${종목코드}_${매매일자 yyyymmdd}` ``, 값 `ProfitEntry[]`.
    - 실패/미지원 시 **빈 Map** 반환(전체 측정 불가로 귀결).
  - `getRealTradeHistory` 반환 항목에 SELL 한정 `roi`·`roiAmount` 포함(BUY는 없음).

- [ ] **Step 1: 실현손익 조회 함수 추가**

`src/lib/kis-api.ts`의 `getRealTradeHistory` 정의 바로 위에 추가한다. `SLL_BUY_DVSN_CD` 등 세부 파라미터/응답 필드명은 **첫 실호출 로그로 실제 키를 확인해 확정**한다(아래는 KIS 문서 기준 초안; `console.log(JSON.stringify(res.data.output1?.[0]))`로 실제 키 검증).

```typescript
/**
 * 기간별 매매손익현황(TTTC8715R)으로 매도 건별 실현손익을 조회해
 * `종목코드_매매일자(yyyymmdd)` 키의 버킷 Map으로 반환한다.
 * 모의투자 미지원/조회 실패 시 빈 Map(→ 전체 "측정 불가").
 */
export async function getRealizedProfitBuckets(
    fromDateStr: string,
    toDateStr: string,
): Promise<Map<string, ProfitEntry[]>> {
    const buckets = new Map<string, ProfitEntry[]>();
    try {
        const config = getKISConfig();
        if (config.IS_VIRTUAL) {
            console.warn('[KIS-API] 모의투자: 기간별매매손익(TTTC8715R) 미지원 가능 → 실현손익 생략');
        }
        const token = await getAccessToken();
        const fullAccount = (config.ACCOUNT_NO || '').replace(/[-\s]/g, '').trim();
        const CANO = fullAccount.slice(0, 8);
        const ACNT_PRDT_CD = fullAccount.slice(8, 10) || '01';

        const res = await axios.get(
            `${config.BASE_URL}/uapi/domestic-stock/v1/trading/inquire-period-trade-profit`,
            {
                headers: {
                    'Content-Type': 'application/json',
                    'authorization': `Bearer ${token}`,
                    'appkey': config.APP_KEY,
                    'appsecret': config.APP_SECRET,
                    'tr_id': 'TTTC8715R',
                    'custtype': 'P',
                },
                params: {
                    CANO,
                    ACNT_PRDT_CD,
                    SORT_DVSN: '00',
                    PDNO: '',
                    INQR_STRT_DT: fromDateStr,
                    INQR_END_DT: toDateStr,
                    CBLC_DVSN: '00',
                    CTX_AREA_FK100: '',
                    CTX_AREA_NK100: '',
                },
                timeout: 10000,
            },
        );

        if (res.data.rt_cd !== '0') {
            console.error(`[KIS-API] 매매손익 조회 실패: ${res.data.msg1}`);
            return buckets;
        }

        const output1: any[] = res.data.output1 || [];
        console.log(`[KIS-API] 매매손익 ${output1.length}건 조회 완료`);
        if (output1[0]) console.log('[KIS-API] 매매손익 샘플 키:', JSON.stringify(output1[0]));

        for (const item of output1) {
            // ↓ 필드명은 첫 실호출 로그로 확정 (초안: KIS 문서 기준)
            const code: string = item.pdno;
            const dt: string = item.trad_dt;                 // yyyymmdd
            const sellQty = Number(item.sll_qty || 0);       // 매도수량
            const roiAmount = Number(item.rlzt_pfls || 0);   // 실현손익(원)
            const rate = Number(item.pfls_rt || 0);          // 손익률(%)
            if (!code || !dt || sellQty <= 0) continue;
            const key = `${code}_${dt}`;
            const roiPct = (rate >= 0 ? '+' : '') + rate.toFixed(1);
            const entry: ProfitEntry = { sellQty, roiPct, roiAmount };
            const arr = buckets.get(key);
            if (arr) arr.push(entry); else buckets.set(key, [entry]);
        }
        return buckets;
    } catch (e: any) {
        const msg = e.response?.data?.msg1 || e.message;
        console.error('[KIS-API] getRealizedProfitBuckets Error:', msg);
        return buckets; // 빈 Map → 측정 불가
    }
}
```

- [ ] **Step 2: `getRealTradeHistory`에서 두 API 호출 + 조인**

`getRealTradeHistory`의 `return output1.map(...)` 부분을 수정한다. 기존 매핑 결과를 변수에 담고, 실현손익 버킷을 조회한 뒤 `matchRealizedRoi`로 조인해 반환한다. 기존 `roi: item.evlu_pfls_rt || '-'` 라인은 **제거**(SELL은 조인으로, BUY는 프론트에서 `-`).

기존:
```typescript
        return output1.map((item: any) => ({
            time: `${item.ord_dt?.slice(0,4)}-${item.ord_dt?.slice(4,6)}-${item.ord_dt?.slice(6,8)} ${item.ord_tmd?.slice(0,2)}:${item.ord_tmd?.slice(2,4)}:${item.ord_tmd?.slice(4,6)}`,
            symbol:       `${item.prdt_name}(${item.pdno})`,   // 종목명(코드)
            code:         item.pdno,
            name:         item.prdt_name,
            action:       item.sll_buy_dvsn_cd === '01' ? 'SELL' : 'BUY',
            price:        item.avg_prvs || item.ccld_avg_unpr || '0',  // 체결평균가
            qty:          item.tot_ccld_qty || '0',                     // 체결수량
            amount:       item.tot_ccld_amt || '0',                     // 체결금액
            roi:          item.evlu_pfls_rt || '-',                     // 평가손익률
            type:         'real',
        }));
```

변경 후:
```typescript
        const fills = output1.map((item: any) => ({
            time: `${item.ord_dt?.slice(0,4)}-${item.ord_dt?.slice(4,6)}-${item.ord_dt?.slice(6,8)} ${item.ord_tmd?.slice(0,2)}:${item.ord_tmd?.slice(2,4)}:${item.ord_tmd?.slice(4,6)}`,
            symbol:       `${item.prdt_name}(${item.pdno})`,   // 종목명(코드)
            code:         item.pdno,
            name:         item.prdt_name,
            action:       (item.sll_buy_dvsn_cd === '01' ? 'SELL' : 'BUY') as 'SELL' | 'BUY',
            price:        item.avg_prvs || item.ccld_avg_unpr || '0',  // 체결평균가
            qty:          item.tot_ccld_qty || '0',                     // 체결수량
            amount:       item.tot_ccld_amt || '0',                     // 체결금액
            type:         'real',
        }));

        // 매도 건에 실현손익(roi %, roiAmount 원) 조인
        const buckets = await getRealizedProfitBuckets(fromDateStr, toDateStr);
        return matchRealizedRoi(fills, buckets);
```

- [ ] **Step 3: 타입체크(빌드)**

Run: `npm run build`
Expected: 빌드 성공. `matchRealizedRoi(fills, buckets)`의 `fills` 타입이 `RealFill[]`와 호환(구조적) — 에러 시 `action` 캐스팅/타입 조정.

- [ ] **Step 4: 실호출 로그로 응답 필드 확정 (실계좌 한정)**

개발 서버를 띄우고 실거래 히스토리 API를 1회 호출해 실제 응답 키를 확인한다.

Run:
```bash
npm run dev   # 별도 터미널
# 다른 터미널에서:
curl -s "http://localhost:3000/api/trade/history?cb=$(date +%s)" > /dev/null
```
Expected(서버 로그): `[KIS-API] 매매손익 N건 조회 완료` 와 `[KIS-API] 매매손익 샘플 키: {...}` 출력.
확인: 로그의 실제 키가 Step 1의 `pdno`/`trad_dt`/`sll_qty`/`rlzt_pfls`/`pfls_rt`와 일치하는지 대조.
**불일치 시** Step 1의 필드 매핑을 실제 키로 수정하고 Step 3~4 재실행.
모의투자(`KIS_IS_VIRTUAL=true`)면 조회 실패/빈 Map이 정상 — 전체 "측정 불가"로 귀결됨을 확인.

- [ ] **Step 5: Commit (사용자 승인 후)**

```bash
git add src/lib/kis-api.ts
git commit -m "feat(trade): 실거래 매도 ROI를 기간별매매손익 API로 계산·조인"
```

---

## Task 3: 프론트 ROI(%)·ROI(금액) 2개 열 표시

**Files:**
- Modify: `src/app/trade/TradeClient.tsx` (`renderHistoryTable` real 분기: 헤더 + 셀)

**Interfaces:**
- Consumes: 히스토리 항목의 `action`('BUY'|'SELL'), `roi?`(부호 문자열), `roiAmount?`(number). real 타입만 해당.

- [ ] **Step 1: 헤더에 ROI(금액) 열 추가**

`renderHistoryTable`의 헤더에서 real일 때 ROI(%) 뒤에 ROI(금액) 헤더를 추가한다.

기존:
```tsx
                            {targetType === 'real' && <Table.Th style={{ fontSize: '11px', textAlign: 'center' }}>ROI(%)</Table.Th>}
```
변경 후:
```tsx
                            {targetType === 'real' && <Table.Th style={{ fontSize: '11px', textAlign: 'center' }}>ROI(%)</Table.Th>}
                            {targetType === 'real' && <Table.Th style={{ fontSize: '11px', textAlign: 'right' }}>ROI(금액)</Table.Th>}
```

- [ ] **Step 2: 셀 렌더 — ROI(%) 분기 정비 + ROI(금액) 셀 추가**

real 셀 렌더 블록을 아래로 교체한다. BUY는 두 열 `-`, 매칭실패 SELL은 "측정 불가", 성공 SELL은 값.

기존:
```tsx
                                {targetType === 'real' && (
                                    <Table.Td style={{ textAlign: 'center' }}>
                                        {h.roi && h.roi !== '-' ? (
                                            <Badge color={h.roi?.startsWith('+') ? 'red' : h.roi?.startsWith('-') ? 'blue' : 'gray'} variant="light" size="xs">
                                                {h.roi}
                                            </Badge>
                                        ) : (
                                            <Text size="xs" c="dimmed">-</Text>
                                        )}
                                    </Table.Td>
                                )}
```
변경 후:
```tsx
                                {targetType === 'real' && (() => {
                                    const isSell = h.action === 'SELL';
                                    const hasRoi = h.roi !== undefined && h.roi !== null && h.roi !== '-';
                                    const roiColor = h.roi?.startsWith('+') ? 'red' : h.roi?.startsWith('-') ? 'blue' : 'gray';
                                    const amtColor = (h.roiAmount ?? 0) > 0 ? 'red' : (h.roiAmount ?? 0) < 0 ? 'blue' : 'gray';
                                    return (
                                        <>
                                            <Table.Td style={{ textAlign: 'center' }}>
                                                {hasRoi ? (
                                                    <Badge color={roiColor} variant="light" size="xs">{h.roi}%</Badge>
                                                ) : (
                                                    <Text size="xs" c="dimmed">{isSell ? '측정 불가' : '-'}</Text>
                                                )}
                                            </Table.Td>
                                            <Table.Td style={{ textAlign: 'right' }}>
                                                {hasRoi && h.roiAmount !== undefined ? (
                                                    <Text size="xs" c={amtColor} fw={600}>
                                                        {(h.roiAmount > 0 ? '+' : '') + h.roiAmount.toLocaleString()}원
                                                    </Text>
                                                ) : (
                                                    <Text size="xs" c="dimmed">{isSell ? '측정 불가' : '-'}</Text>
                                                )}
                                            </Table.Td>
                                        </>
                                    );
                                })()}
```

- [ ] **Step 3: 타입체크(빌드)**

Run: `npm run build`
Expected: 빌드 성공.

- [ ] **Step 4: 브라우저 육안 검증**

`npm run dev` 후 `/trade` 페이지의 "실거래 매매 히스토리" 확인:
- BUY 행: ROI(%)·ROI(금액) 모두 `-`.
- 원가 확보된 SELL: ROI(%) 뱃지(+빨강/−파랑) + ROI(금액) `+12,400원`/`-3,200원`.
- 원가 미확보 SELL(또는 모의투자): 두 열 dimmed "측정 불가".
- 가로 스크롤/열 정렬 깨짐 없음.

- [ ] **Step 5: Commit (사용자 승인 후)**

```bash
git add src/app/trade/TradeClient.tsx
git commit -m "feat(trade): 실거래 히스토리에 ROI(%)·ROI(금액) 열 표시"
```

---

## Self-Review

**Spec coverage:**
- 실현손익 API(TTTC8715R) 소스 → Task 2 Step 1. ✓
- 조인/FIFO(종목+일자) → Task 1. ✓
- BUY=`-`, 매칭실패 SELL="측정 불가" → Task 1(값 미부여) + Task 3(렌더 분기). ✓
- 모의투자 리스크(전체 측정 불가) → Task 2 Step 1/Step 4. ✓
- ROI(%)·ROI(금액) 2개 열 → Task 3. ✓
- 필드명 실호출 검증 → Task 2 Step 4. ✓
- 시뮬 히스토리 불변 → 모든 변경이 `targetType === 'real'`/real 항목 한정. ✓

**Placeholder scan:** "필드명 실호출로 확정"은 spec이 명시한 검증 절차(Task 2 Step 4에 구체적 실행/판정 포함)로, 미완 placeholder 아님. 그 외 TODO/TBD 없음.

**Type consistency:** `matchRealizedRoi`/`ProfitEntry`/`getRealizedProfitBuckets` 시그니처가 Task 1↔2에서 일치. 프론트는 `roi`(string)·`roiAmount`(number)·`action`만 소비 — Task 2 반환과 일치.
