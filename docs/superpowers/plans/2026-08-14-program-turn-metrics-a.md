# 프로그램 매매 지표 턴 기준 재정의 (ⓐ) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실전 계좌 화면의 `프로그램 매매` 블록을 현재 턴 기준으로 통일하고, 실제로 낸 수수료를 차감한 net 손익과 지난 턴 이력을 보여준다.

**Architecture:** 수수료 요율의 단일 정의는 `src/trade/fees.py`에 그대로 두고, 파이썬이 원장에 `turn.fees_realized`(누적 실현 비용)와 `ledger['fee_rates']`(요율 사본)를 적는다. TS는 요율을 복사하지 않고 원장에서 읽어 보유분 매수 수수료를 유도한다. 화면 계산은 전부 `src/lib/`의 순수 함수에 있고 node 테스트가 지킨다.

**Tech Stack:** Python 3.12 + pytest / TypeScript + `node --test` / Next.js + Mantine

**Spec:** `docs/superpowers/specs/2026-08-14-program-turn-metrics-design.md`

## Global Constraints

- 못 구한 값은 `null`로 올려 화면이 "측정 불가"로 그린다. **0으로 폴백 금지** — `[[no-fabricated-financial-values]]`
- 수수료 요율 상수는 `src/trade/fees.py`에만 존재한다. TS에 복사하지 않는다 — 복사가 곧 2026-08-10 버그의 형태였다
- 파이썬 테스트: `python -m pytest tests/<file> -v`
- TS 테스트: `node --test "src/**/*.test.ts"` — 테스트 파일 import는 `.ts` 확장자를 반드시 붙인다
- 타입체크: `npx tsc --noEmit`
- 커밋 메시지가 여러 줄이면 파일로 넘긴다: `git commit -F <파일>`
- 이 계획은 **표시·기록 계층만** 건드린다. 주문·정산 로직의 판단은 바꾸지 않는다

---

### Task 1: 왕복 거래비용 헬퍼

`realized_pnl_after_fees`는 비용을 뺀 결과만 돌려주고 "얼마를 뺐는지"는 버린다. 화면이 그 값을 보여줘야 하므로 비용만 따로 내는 함수가 필요하다.

**Files:**
- Modify: `src/trade/fees.py`
- Test: `tests/test_trade_fees.py`

**Interfaces:**
- Produces: `roundtrip_cost(qty: int, buy_price: float, sell_price: float) -> float`

- [ ] **Step 1: Write the failing test**

`tests/test_trade_fees.py` 끝에 추가:

```python
from src.trade.fees import roundtrip_cost, buy_cost, sell_cost


def test_roundtrip_cost_is_buy_plus_sell():
    """왕복 비용 = 매수 수수료 + (매도 수수료 + 거래세)."""
    got = roundtrip_cost(10, 1000.0, 1100.0)
    assert got == buy_cost(10, 1000.0) + sell_cost(10, 1100.0)


def test_roundtrip_cost_is_what_realized_pnl_subtracted():
    """손익에서 뺀 비용과 정확히 같은 값이어야 한다 — 다르면 화면 검산이 깨진다."""
    from src.trade.fees import realized_pnl_after_fees
    gross = 10 * (1100.0 - 1000.0)
    net = realized_pnl_after_fees(10, 1000.0, 1100.0)
    assert abs((gross - net) - roundtrip_cost(10, 1000.0, 1100.0)) < 1e-9


def test_roundtrip_cost_zero_qty_is_zero():
    assert roundtrip_cost(0, 1000.0, 1100.0) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_trade_fees.py -v -k roundtrip`
Expected: FAIL — `ImportError: cannot import name 'roundtrip_cost'`

- [ ] **Step 3: Write minimal implementation**

`src/trade/fees.py`의 `realized_pnl_after_fees` 바로 위에 추가:

```python
def roundtrip_cost(qty: int, buy_price: float, sell_price: float) -> float:
    """`realized_pnl_after_fees`가 빼는 비용과 **정확히 같은 값**.

    손익에서 뺀 금액을 화면이 "수수료 N원 차감"으로 보여주려면 그 값을 따로
    낼 수 있어야 한다. 두 함수가 갈리면 화면의 검산(gross - 수수료 = net)이
    깨지므로, 항이 바뀌면 반드시 함께 바꾼다.
    """
    return buy_cost(qty, buy_price) + sell_cost(qty, sell_price)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_trade_fees.py -v`
Expected: PASS (기존 테스트 포함 전부)

- [ ] **Step 5: Commit**

```bash
git add src/trade/fees.py tests/test_trade_fees.py
git commit -m "feat(fees): 손익에서 뺀 왕복 비용을 따로 낼 수 있게 한다"
```

---

### Task 2: 턴 실현 수수료 누적

**Files:**
- Modify: `src/pipeline/workers/program_trader.py` (`accrue_realized_pnl`, 49-69행)
- Modify: `src/trade/pending.py` (`_correct_sell`, 132-183행)
- Test: `tests/test_program_turn_fees.py` (신규)

**Interfaces:**
- Consumes: `roundtrip_cost` (Task 1)
- Produces: 원장 필드 `ledger['turn']['fees_realized']: float` — 이 턴에서 매도로 실제 발생한 왕복 비용의 누적

**설계 메모:** 손익과 **같은 텔레스코핑**을 쓴다. 매도 주문 시 추정 비용을 더하고, 정산 때 `실측 − 추정`만 보정한다. `realized_override`(KIS 확정) 경로는 KIS가 비용을 분해해 주지 않으므로 우리 모델의 값으로 남는다 — 그 괴리를 잡는 것이 ⓑ 대사기의 일이다.

- [ ] **Step 1: Write the failing test**

`tests/test_program_turn_fees.py` 생성:

```python
"""턴 수수료 누적 — 화면의 '수수료 N원 차감'이 손익에서 실제로 뺀 값과 같아야 한다."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.program_trader import accrue_realized_pnl
from src.trade.fees import roundtrip_cost
from src.trade.pending import _correct_sell


def _ledger():
    return {'realized_pnl': 0.0, 'turn': {'id': 't1', 'by_tag': {}, 'fees_realized': 0.0}}


def test_sell_order_accrues_estimated_fees():
    led = _ledger()
    positions = {'005930': {'avg_price': 1000.0, 'quantity': 10}}

    accrue_realized_pnl(led, positions, '005930', 10, 1100.0)

    assert led['turn']['fees_realized'] == roundtrip_cost(10, 1000.0, 1100.0)


def test_settlement_corrects_fees_to_actual():
    """전량 주문했는데 6주만 체결 — 수수료도 6주분으로 줄어야 한다."""
    led = _ledger()
    positions = {}
    led['turn']['fees_realized'] = roundtrip_cost(10, 1000.0, 1100.0)
    p = {'qty': 10, 'price': 1100.0, 'avg_price': 1000.0, 'tag': 'sim4'}

    _correct_sell(led, positions, '005930', p, filled_qty=6, fill_px=1090.0)

    assert abs(led['turn']['fees_realized'] - roundtrip_cost(6, 1000.0, 1090.0)) < 1e-9


def test_unfilled_sell_removes_the_accrued_fee():
    """한 주도 안 팔렸으면 비용도 0으로 되돌아간다 — 안 낸 돈이 남으면 안 된다."""
    led = _ledger()
    led['turn']['fees_realized'] = roundtrip_cost(10, 1000.0, 1100.0)
    p = {'qty': 10, 'price': 1100.0, 'avg_price': 1000.0, 'tag': 'sim4'}

    _correct_sell(led, {}, '005930', p, filled_qty=0, fill_px=0.0)

    assert abs(led['turn']['fees_realized']) < 1e-9


def test_no_turn_does_not_crash():
    """턴이 없을 때(프로그램 OFF 중 잔여 정산)도 죽지 않는다."""
    led = {'realized_pnl': 0.0}
    accrue_realized_pnl(led, {'005930': {'avg_price': 1000.0, 'quantity': 10}},
                        '005930', 10, 1100.0)
    _correct_sell(led, {}, '005930',
                  {'qty': 10, 'price': 1100.0, 'avg_price': 1000.0}, 0, 0.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_program_turn_fees.py -v`
Expected: FAIL — `assert 0.0 == 2.85` (fees_realized가 안 쌓임)

- [ ] **Step 3: Write minimal implementation**

`src/pipeline/workers/program_trader.py` — import 줄에 `roundtrip_cost`를 더하고(`from src.trade.fees import realized_pnl_after_fees` 옆), `accrue_realized_pnl`의 `ledger['realized_pnl'] = ...` 다음 줄에 추가:

```python
    _accrue_turn_fees(ledger, roundtrip_cost(qty, pos['avg_price'], price))
```

같은 파일 `accrue_realized_pnl` 바로 아래에 추가:

```python
def _accrue_turn_fees(ledger: dict, delta: float) -> None:
    """턴의 실현 비용 누적. 턴이 없으면 아무것도 하지 않는다(OFF 중 잔여 정산)."""
    turn = ledger.get('turn')
    if turn is None:
        return
    turn['fees_realized'] = turn.get('fees_realized', 0.0) + delta
```

`src/trade/pending.py` — import에 `roundtrip_cost`를 더하고, `_correct_sell`의 `ledger['realized_pnl'] = ledger.get('realized_pnl', 0) + correction` 다음에 추가:

```python
    # 손익과 같은 텔레스코핑. 주문 시 더한 추정 비용을 실측으로 갈아끼운다.
    # realized_override(KIS 확정) 경로는 KIS가 비용을 분해해 주지 않으므로
    # 우리 모델 값으로 남는다 — 그 괴리는 체결 대사가 잡는다.
    est_fee = roundtrip_cost(p['qty'], avg, p['price']) if avg else 0.0
    act_fee = roundtrip_cost(filled_qty, avg, fill_px or p['price']) if (avg and filled_qty) else 0.0
    turn = ledger.get('turn')
    if turn is not None:
        turn['fees_realized'] = turn.get('fees_realized', 0.0) + (act_fee - est_fee)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_program_turn_fees.py tests/test_pending_reconcile.py tests/test_program_realized_pnl.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/workers/program_trader.py src/trade/pending.py tests/test_program_turn_fees.py
git commit -m "feat(program): 턴이 실제로 낸 매매 비용을 원장에 남긴다"
```

---

### Task 3: 요율을 원장에 실어 TS가 복사하지 않게 한다

TS는 보유분 매수 수수료를 계산해야 하지만, 요율 상수를 복사하면 2026-08-10 버그(심과 실전의 비용 모델이 갈림)를 그대로 재현한다. 파이썬이 요율을 원장에 적고 TS가 읽는다.

**Files:**
- Modify: `src/pipeline/workers/program_trader.py` (`ledger['last_run'] = ...` 인근 1202행, 1339행 두 곳)
- Test: `tests/test_program_fee_rates.py` (신규)

**Interfaces:**
- Produces: 원장 필드 `ledger['fee_rates'] = {'buy': float, 'sell': float, 'tax': float}`

- [ ] **Step 1: Write the failing test**

`tests/test_program_fee_rates.py` 생성:

```python
"""요율은 fees.py에만 산다. 원장에 싣는 이유는 TS가 복사하지 않게 하려는 것이다."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.program_trader import stamp_fee_rates
from src.trade import fees


def test_stamps_the_rates_from_the_single_definition():
    led = {}
    stamp_fee_rates(led)
    assert led['fee_rates'] == {
        'buy': fees.BUY_FEE_RATE,
        'sell': fees.SELL_FEE_RATE,
        'tax': fees.SELL_TAX_RATE,
    }


def test_stamping_twice_is_idempotent():
    led = {}
    stamp_fee_rates(led)
    first = dict(led['fee_rates'])
    stamp_fee_rates(led)
    assert led['fee_rates'] == first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_program_fee_rates.py -v`
Expected: FAIL — `ImportError: cannot import name 'stamp_fee_rates'`

- [ ] **Step 3: Write minimal implementation**

`src/pipeline/workers/program_trader.py`의 `_accrue_turn_fees` 아래에 추가:

```python
def stamp_fee_rates(ledger: dict) -> None:
    """요율 사본을 원장에 찍는다. **정의는 fees.py 하나뿐이다.**

    화면(TS)이 보유분 매수 수수료를 유도해야 하는데, 상수를 TS에 복사하면
    2026-08-10에 심과 실전의 비용 모델이 갈렸던 버그를 그대로 재현한다.
    복사 대신 매 사이클 원장에 실어 보낸다.
    """
    from src.trade import fees
    ledger['fee_rates'] = {'buy': fees.BUY_FEE_RATE,
                           'sell': fees.SELL_FEE_RATE,
                           'tax': fees.SELL_TAX_RATE}
```

같은 파일에서 `ledger['last_run'] = now_kst.isoformat()`가 나오는 **두 곳**(1202행, 1339행 부근) 각각 바로 아래에 추가:

```python
        stamp_fee_rates(ledger)
```

(들여쓰기는 그 자리의 기존 줄과 맞춘다. 1339행 쪽은 들여쓰기가 4칸이다.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_program_fee_rates.py tests/test_program_turn.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/workers/program_trader.py tests/test_program_fee_rates.py
git commit -m "feat(program): 수수료 요율을 원장에 실어 화면이 상수를 복사하지 않게 한다"
```

---

### Task 4: `opening_basis` 폐기 — 턴 기준가를 평단으로 통일

**Files:**
- Modify: `src/app/api/trade/program/route.ts` (ON 핸들러 `opened` IIFE 370-385행, 폴백 턴 262-275행)
- Test: `src/lib/program-turn.test.ts`

**Interfaces:**
- Consumes: `ProgramPosition.avg_price`
- Produces: `basisFromPositions(positions: Record<string, ProgramPosition>): Record<string, number>` (`src/lib/program-turn.ts`)

**왜:** 지금 route.ts는 ON 시점 **현재가**로 `opening_basis`를 만들고, 파이썬 `new_turn`은 **매입 평단**으로 basis를 만들며 `opening_basis`를 의도적으로 무시한다. 그런데 route.ts의 폴백 턴(파이썬 첫 실행 전)이 그 무시당하는 값을 쓴다 → 같은 턴의 손익이 파이썬 첫 런 전후로 점프한다.

- [ ] **Step 1: Write the failing test**

`src/lib/program-turn.test.ts` 끝에 추가:

```typescript
import { basisFromPositions } from './program-turn.ts';

test('턴 기준가는 매입 평단이다 — ON 시점 시세로 리셋하지 않는다', () => {
  // 파이썬 new_turn과 같은 규칙. 갈리면 파이썬 첫 런 전후로 턴 손익이 점프한다.
  const positions = {
    A: { name: '가', quantity: 10, avg_price: 1000 },
    B: { name: '나', quantity: 5, avg_price: 2000 },
  };
  assert.deepEqual(basisFromPositions(positions), { A: 1000, B: 2000 });
});

test('평단이 없거나 0인 종목은 기준가를 만들지 않는다', () => {
  // 0을 넣으면 (현재가 - 0) * 수량 = 시가총액 전체가 턴 수익이 된다.
  const positions = { A: { name: '가', quantity: 10, avg_price: 0 } } as any;
  assert.deepEqual(basisFromPositions(positions), {});
});

test('보유가 없으면 빈 기준가다', () => {
  assert.deepEqual(basisFromPositions({}), {});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test src/lib/program-turn.test.ts`
Expected: FAIL — `basisFromPositions is not a function`

- [ ] **Step 3: Write minimal implementation**

`src/lib/program-turn.ts` 끝에 추가:

```typescript
/**
 * 턴 기준가 = 보유 종목의 **매입 평단**. 파이썬 new_turn과 같은 규칙이다.
 *
 * ON 시점 시세로 리셋(MTM)하지 않는다 — ON 전부터 보유한 종목도 원래 매입가부터
 * 재야 KIS 종목별 ROI와 턴 손익이 정합한다. 예전에는 route가 현재가로,
 * 파이썬이 평단으로 잡아 파이썬 첫 런 전후로 같은 턴의 손익이 점프했다.
 *
 * avg_price가 0/누락이면 항목을 만들지 않는다. 0을 기준가로 넣으면
 * (현재가 - 0) * 수량, 즉 시가총액 전체가 턴 수익으로 계상된다.
 */
export function basisFromPositions(
    positions: Record<string, ProgramPosition>,
): Record<string, number> {
    const basis: Record<string, number> = {};
    for (const [code, pos] of Object.entries(positions || {})) {
        const avg = Number(pos?.avg_price) || 0;
        if (avg > 0) basis[code] = avg;
    }
    return basis;
}
```

`src/app/api/trade/program/route.ts` — import에 `basisFromPositions`를 더한다. ON 핸들러의 `opened` IIFE를 다음으로 교체:

```typescript
        const opened = await withDeadline((async () => {
            const { ok: ledgerOk, positions, realized_pnl } = await getPositions();
            // 조회 실패/데드라인 초과 시 capital은 falsy(0)로 남긴다 — 그럴듯한 값을 지어내는 대신
            // 파이썬의 `cfg_turn.get('capital') or effective_budget` 폴백이 채우게 한다.
            const capital = ledgerOk ? budgetNum + realized_pnl : 0;   // 턴 시작 유효자본
            // 기준가는 매입 평단이다(basisFromPositions 주석 참고). 시세 조회가 필요 없어졌다.
            return { capital, opening_basis: basisFromPositions(positions) };
        })(), DISPLAY_DEADLINE_MS, { capital: 0, opening_basis: {} });
```

폴백 턴(262-275행 부근)의 주석 중 "ON 시점의 시세로 ... 스냅샷한다(MTM 리셋)"를 "기준가는 매입 평단이다"로 고친다. `basis: cfgTurn.opening_basis || {}`는 그대로 둔다 — 이제 그 값이 평단이므로 파이썬과 일치한다.

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test "src/**/*.test.ts"` 그리고 `npx tsc --noEmit`
Expected: 전부 PASS, 타입 에러 없음

- [ ] **Step 5: Commit**

```bash
git add src/lib/program-turn.ts src/lib/program-turn.test.ts src/app/api/trade/program/route.ts
git commit -m "fix(trade): 턴 기준가를 매입 평단으로 통일한다"
```

---

### Task 5: 턴 이력 배열

**Files:**
- Create: `src/lib/turn-history.ts`
- Create: `src/lib/turn-history.test.ts`
- Modify: `src/app/api/trade/program/route.ts` (OFF 핸들러 320-337행, GET 응답 290행 부근)

**Interfaces:**
- Consumes: `LastTurnResult` (`src/lib/program-turn.ts`)
- Produces:
  - `export const TURN_HISTORY_MAX = 20`
  - `pushTurnHistory(history: LastTurnResult[] | null | undefined, entry: LastTurnResult): LastTurnResult[]`

- [ ] **Step 1: Write the failing test**

`src/lib/turn-history.test.ts` 생성:

```typescript
import { test } from 'node:test';
import assert from 'node:assert';
import { pushTurnHistory, TURN_HISTORY_MAX } from './turn-history.ts';

const turn = (id: string, pnl: number | null = 0) => ({
  id, ended_at: `2026-08-14T${id.padStart(2, '0')}:00:00`, started_at: '2026-08-01T09:00:00',
  sim: 'sim4', capital: 2_000_000, pnl, by_tag: {}, fees: 0,
});

test('가장 최근 턴이 맨 앞에 온다', () => {
  const h = pushTurnHistory([turn('1')], turn('2'));
  assert.deepEqual(h.map((t) => t.id), ['2', '1']);
});

test('이력이 없던 상태에서도 첫 턴이 들어간다', () => {
  for (const empty of [null, undefined, []]) {
    assert.equal(pushTurnHistory(empty as any, turn('1')).length, 1);
  }
});

test(`${TURN_HISTORY_MAX}개를 넘으면 가장 오래된 것이 빠진다`, () => {
  // config는 GitHub 파일이라 무한히 키울 수 없다.
  let h: any[] = [];
  for (let i = 1; i <= TURN_HISTORY_MAX + 1; i++) h = pushTurnHistory(h, turn(String(i)));

  assert.equal(h.length, TURN_HISTORY_MAX);
  assert.equal(h[0].id, String(TURN_HISTORY_MAX + 1), '최신이 앞');
  assert.ok(!h.some((t) => t.id === '1'), '가장 오래된 것이 빠져야 한다');
});

test('측정 불가 턴도 그대로 남는다 — 실패를 지우면 실패한 적이 없어 보인다', () => {
  const h = pushTurnHistory([], turn('1', null));
  assert.equal(h[0].pnl, null);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test src/lib/turn-history.test.ts`
Expected: FAIL — 모듈을 찾지 못함

- [ ] **Step 3: Write minimal implementation**

`src/lib/turn-history.ts` 생성:

```typescript
/**
 * 종료된 턴의 이력. 화면의 '지난 턴' 목록이 읽는다.
 *
 * 모든 지표가 현재 턴 기준이 되면서, 껐다 켠 순간 이전 성과가 화면에서 사라진다.
 * 이 목록이 그걸 받는다.
 */
import type { LastTurnResult } from './program-turn.ts';

/** config는 secret repo의 GitHub 파일이다 — 무한히 키우면 매 OFF마다 커밋이 무거워진다. */
export const TURN_HISTORY_MAX = 20;

/** 최신을 앞에 넣고 상한까지 자른다. `pnl: null`(측정 불가) 턴도 그대로 남긴다. */
export function pushTurnHistory(
    history: LastTurnResult[] | null | undefined,
    entry: LastTurnResult,
): LastTurnResult[] {
    return [entry, ...(history || [])].slice(0, TURN_HISTORY_MAX);
}
```

`src/lib/program-turn.ts`의 `LastTurnResult` 타입에 두 필드를 더한다:

```typescript
export type LastTurnResult = {
    id: string;
    ended_at: string;
    /** 턴이 열린 시각. 없으면 '언제부터'를 그릴 수 없다(구 기록은 없을 수 있다). */
    started_at?: string;
    sim: string | null;
    capital: number;
    pnl: number | null;
    /** 이 턴에 실제로 낸 매매 비용. 계산 불가였으면 null. */
    fees?: number | null;
    by_tag: Record<string, number>;
    degraded?: 'ledger_unavailable' | 'prices_unavailable' | 'timeout';
};
```

`src/app/api/trade/program/route.ts`:
- import에 `pushTurnHistory`를 더한다
- `freezeTurn` 시그니처에 `startedAt: string | undefined`를 더하고 `base`에 `started_at: startedAt`을 넣는다. 수수료는 원장 턴을 찾은 뒤에 넣는다:

```typescript
    // `|| 0`이 아니라 이 순서다 — 원장을 못 읽은 것(null)과 거래가 없어 0원인 것을
    // 합치면 안 된다. 0원은 값이고 null은 '모른다'다.
    const fees = matched ? Number(matched.fees_realized ?? 0) : 0;
```

`ledgerOk === false`인 경로(`degraded: 'ledger_unavailable'`)에서만 `fees: null`이다
- OFF 핸들러에서 `freezeTurn(cfgTurn, sim, now)` → `freezeTurn(cfgTurn, sim, now, cfgTurn.started_at)`
- OFF 핸들러의 `const next = {...}`에서 `last_turn_result: lastTurnResult`를 다음으로 교체:

```typescript
                turn: null,
                last_turn_result: lastTurnResult,
                turn_history: lastTurnResult
                    ? pushTurnHistory(content.turn_history, lastTurnResult)
                    : (content.turn_history ?? []),
```

(`last_turn_result`는 남긴다 — 진행 중인 턴이 없을 때 화면이 직전 턴을 그리는 데 계속 쓴다.)

- GET 응답에 한 줄 추가:

```typescript
            turn_history: Array.isArray(content.turn_history) ? content.turn_history : [],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test "src/**/*.test.ts"` 그리고 `npx tsc --noEmit`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lib/turn-history.ts src/lib/turn-history.test.ts src/lib/program-turn.ts src/app/api/trade/program/route.ts
git commit -m "feat(trade): 종료된 턴을 이력으로 쌓는다"
```

---

### Task 6: 턴 손익을 net으로 — 보유분 매수 수수료 차감

**Files:**
- Modify: `src/lib/program-turn.ts` (`computeTurnPnl`, 56-78행)
- Test: `src/lib/program-turn.test.ts`

**Interfaces:**
- Consumes: `ledger['fee_rates']`(Task 3), `turn.fees_realized`(Task 2)
- Produces: `computeTurnPnl(turn, positions, prices, feeRates?)` 의 반환이
  `{ pnl: number; byTag: Record<string, number>; fees: number | null }`로 바뀐다

**왜:** 지금 `by_tag`는 실현분이 net(비용 차감), 미실현분이 gross(비용 미차감)로 섞여 있다. 전략별 기여도의 합계가 화면의 평가손익(net)과 맞으려면 미실현 쪽에서도 **이미 낸 매수 수수료**를 빼야 한다.

- [ ] **Step 1: Write the failing test**

`src/lib/program-turn.test.ts` 끝에 추가:

```typescript
const RATES = { buy: 0.00015, sell: 0.00015, tax: 0.0018 };

test('보유분의 매수 수수료를 미실현에서 뺀다 — 이미 낸 돈이다', () => {
  const turn = { id: 't1', capital: 1_000_000, basis: { A: 1000 }, by_tag: {}, active_tag: 'sim4',
                 fees_realized: 0 } as any;
  const positions = { A: { name: '가', quantity: 100, avg_price: 1000, tag: 'sim4' } };

  const { pnl, byTag, fees } = computeTurnPnl(turn, positions, { A: 1100 }, RATES);

  const buyFee = 100 * 1000 * RATES.buy;          // 15원
  assert.equal(fees, buyFee);
  assert.equal(pnl, 100 * (1100 - 1000) - buyFee); // gross 10,000 - 15
  assert.equal(byTag.sim4, pnl, '기여도 합계는 전체 손익과 같아야 한다');
});

test('아직 안 낸 매도 비용은 미리 빼지 않는다', () => {
  const turn = { id: 't1', capital: 1_000_000, basis: { A: 1000 }, by_tag: {}, active_tag: 'sim4',
                 fees_realized: 0 } as any;
  const positions = { A: { name: '가', quantity: 100, avg_price: 1000, tag: 'sim4' } };

  const { fees } = computeTurnPnl(turn, positions, { A: 1100 }, RATES);

  // 매도 수수료(0.00015) + 거래세(0.0018)를 미리 뺐다면 값이 훨씬 커진다.
  assert.equal(fees, 100 * 1000 * RATES.buy);
});

test('실현 비용과 보유분 매수 수수료를 합쳐 낸다', () => {
  const turn = { id: 't1', capital: 1_000_000, basis: { A: 1000 }, by_tag: { sim4: 5_000 },
                 active_tag: 'sim4', fees_realized: 300 } as any;
  const positions = { A: { name: '가', quantity: 100, avg_price: 1000, tag: 'sim4' } };

  const { fees } = computeTurnPnl(turn, positions, { A: 1100 }, RATES);

  assert.equal(fees, 300 + 100 * 1000 * RATES.buy);
});

test('요율이 없으면 수수료는 0이 아니라 측정 불가다', () => {
  // 원장에 fee_rates가 아직 안 찍힌 첫 배포 직후. 0으로 그리면 '수수료를 안 냈다'는 거짓이 된다.
  const turn = { id: 't1', capital: 1_000_000, basis: { A: 1000 }, by_tag: {}, active_tag: 'sim4',
                 fees_realized: 0 } as any;
  const positions = { A: { name: '가', quantity: 100, avg_price: 1000, tag: 'sim4' } };

  const { fees, pnl } = computeTurnPnl(turn, positions, { A: 1100 }, undefined);

  assert.equal(fees, null);
  assert.equal(pnl, 100 * (1100 - 1000), '차감할 수 없으면 gross 그대로 둔다');
});

test('시세를 못 구한 종목은 수수료도 안 뺀다 — 손익을 안 세는 종목이다', () => {
  const turn = { id: 't1', capital: 1_000_000, basis: { A: 1000 }, by_tag: {}, active_tag: 'sim4',
                 fees_realized: 0 } as any;
  const positions = { A: { name: '가', quantity: 100, avg_price: 1000, tag: 'sim4' } };

  const { pnl, fees } = computeTurnPnl(turn, positions, {}, RATES);

  assert.equal(pnl, 0);
  assert.equal(fees, 0);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test src/lib/program-turn.test.ts`
Expected: FAIL — `fees`가 `undefined`

- [ ] **Step 3: Write minimal implementation**

`src/lib/program-turn.ts`:

```typescript
/** 원장이 실어 보내는 수수료 요율 사본. 정의는 src/trade/fees.py 하나뿐이다. */
export type FeeRates = { buy: number; sell: number; tax: number };

export type TurnResult = {
    pnl: number;
    byTag: Record<string, number>;
    /** 이 턴에 실제로 낸 비용. 요율을 못 받았으면 null(= 측정 불가). */
    fees: number | null;
};
```

`computeTurnPnl`을 교체:

```typescript
export function computeTurnPnl(
    turn: ProgramTurn | null | undefined,
    positions: Record<string, ProgramPosition>,
    prices: Record<string, number>,
    feeRates?: FeeRates,
): TurnResult {
    if (!turn || !turn.id) return { pnl: 0, byTag: {}, fees: feeRates ? 0 : null };

    const byTag: Record<string, number> = { ...(turn.by_tag || {}) };
    const basis = turn.basis || {};
    // 실현 비용은 파이썬이 원장에 누적해 둔 값이다(turn.fees_realized).
    let holdingFee = 0;

    for (const [code, pos] of Object.entries(positions || {})) {
        const px = Number(prices[code]) || 0;
        if (px <= 0) continue;   // 시세 없음 = 손익도 비용도 안 센다
        // ||(falsy 폴백): 파이썬 new_turn()의 `or` 체인과 동일. basis에 0이 들어오면
        // ??는 0을 통과시켜 (px-0)*qty = 시가총액 전체가 턴 수익으로 계상된다.
        const b = Number(basis[code] || px);
        const tag = pos.tag || turn.active_tag || 'unknown';
        // 미실현은 gross다. 이미 지불한 매수 수수료만 빼서 실현분(net)과 눈금을 맞춘다.
        // 아직 안 낸 매도 수수료·거래세는 빼지 않는다 — 안 낸 돈이다.
        const fee = feeRates ? pos.quantity * Number(pos.avg_price || 0) * feeRates.buy : 0;
        holdingFee += fee;
        byTag[tag] = (byTag[tag] || 0) + (px - b) * pos.quantity - fee;
    }

    const pnl = Object.values(byTag).reduce((s, v) => s + v, 0);
    const fees = feeRates ? (Number(turn.fees_realized) || 0) + holdingFee : null;
    return { pnl, byTag, fees };
}
```

`ProgramTurn` 타입에 `fees_realized?: number;`를 더한다.

`freezeTurn`(route.ts)의 `computeTurnPnl(matched, positions, prices)` 호출부는 그대로 둔다 — 요율 없이 부르면 `fees: null`이 되고, `base`의 `fees`는 `matched.fees_realized`에서 온다.

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test "src/**/*.test.ts"` 그리고 `npx tsc --noEmit`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/lib/program-turn.ts src/lib/program-turn.test.ts
git commit -m "feat(trade): 턴 손익에서 이미 낸 매수 수수료를 뺀다"
```

---

### Task 7: 화면 요약값을 턴 기준으로 재정의

**Files:**
- Modify: `src/lib/real-account-summary.ts` (`summarizeProgram` 52-78행, `summarizeTurn` 102-126행)
- Test: `src/lib/real-account-summary.test.ts`

**Interfaces:**
- Consumes: `computeTurnPnl(..., feeRates)` (Task 6)
- Produces: `summarizeTurn`의 반환에 `fees: number | null`, `startedAt: string | null`이 추가된다.
  `summarizeProgram`은 `ratePct`/`totalPnl`을 더 이상 내지 않고 `holdingsValue`·`hasData`만 낸다.

- [ ] **Step 1: Write the failing test**

`src/lib/real-account-summary.test.ts` 끝에 추가:

```typescript
const RATES = { buy: 0.00015, sell: 0.00015, tax: 0.0018 };

test('프로그램 요약은 이제 보유 평가금액만 낸다 — 수익률은 턴이 낸다', () => {
  const p = summarizeProgram({ positions: POS, prices: { A: 1_200 } });
  assert.equal(p.holdingsValue > 0, true);
  assert.equal('ratePct' in p, false, '누적 수익률은 화면에서 사라졌다');
});

test('턴 요약이 수수료와 시작 시각을 낸다', () => {
  const turn = { id: 't1', capital: 1_000_000, basis: { A: 1000 }, by_tag: {},
                 active_tag: 'sim4', fees_realized: 300, started_at: '2026-08-12T14:20:00' } as any;
  const t = summarizeTurn({
    turn, lastTurn: null, positions: { A: { name: '가', quantity: 100, avg_price: 1000, tag: 'sim4' } },
    prices: { A: 1100 }, programEnabled: true, feeRates: RATES,
  });

  assert.equal(t.fees, 300 + 100 * 1000 * RATES.buy);
  assert.equal(t.startedAt, '2026-08-12T14:20:00');
  assert.equal(t.measurable, true);
});

test('요율을 못 받으면 수수료는 측정 불가다', () => {
  const turn = { id: 't1', capital: 1_000_000, basis: {}, by_tag: { sim4: 1000 },
                 active_tag: 'sim4' } as any;
  const t = summarizeTurn({ turn, lastTurn: null, positions: {}, prices: {},
                            programEnabled: true, feeRates: undefined });
  assert.equal(t.fees, null);
});

test('OFF로 동결된 직전 턴도 수수료와 시작 시각을 그대로 쓴다', () => {
  const lastTurn = { id: 't0', ended_at: '2026-08-12T14:20:00', started_at: '2026-08-03T10:00:00',
                     sim: 'sim4', capital: 2_000_000, pnl: 12_340, fees: 2_100, by_tag: {} };
  const t = summarizeTurn({ turn: null, lastTurn, positions: {}, prices: {},
                            programEnabled: false, feeRates: RATES });

  assert.equal(t.fees, 2_100);
  assert.equal(t.startedAt, '2026-08-03T10:00:00');
  assert.equal(t.isLive, false);
});
```

기존 테스트 중 `summarizeProgram`에 `realizedPnl`/`budget`을 넘기고 `ratePct`를 확인하는 것들(59, 70, 77, 83, 85, 86행 부근)은 새 시그니처에 맞춰 고친다 — `realizedPnl`·`budget` 인자를 빼고 `ratePct` 단언을 지운다. `hasData`는 `positions`가 비지 않았는지로만 판정한다.

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test src/lib/real-account-summary.test.ts`
Expected: FAIL — `t.fees`가 `undefined`

- [ ] **Step 3: Write minimal implementation**

`src/lib/real-account-summary.ts`에서 `summarizeProgram`을 교체:

```typescript
/**
 * 프로그램 보유 평가금액.
 *
 * [2026-08-14] 누적 수익률·누적 평가손익은 화면에서 사라졌다 — 모든 지표가 턴
 * 기준이 됐기 때문이다(summarizeTurn). 원장의 realized_pnl은 그대로 살아 있고
 * effective_budget(다음 주문 크기) 계산에 계속 쓰인다.
 *
 * 시세를 못 붙인 종목은 avg_price로 평가한다 — 없는 시세를 지어내지 않는다.
 */
export function summarizeProgram(args: {
    positions: Record<string, ProgramPosition>;
    prices: Record<string, number>;
}): { holdingsValue: number; hasData: boolean } {
    const entries = Object.entries(args.positions || {});
    const holdingsValue = entries.reduce((sum, [code, pos]) => {
        const px = args.prices[code];
        return sum + ((px != null && px > 0 ? px : pos.avg_price) * pos.quantity);
    }, 0);
    return { holdingsValue, hasData: entries.length > 0 };
}
```

`TurnSummary` 타입에 두 필드를 더한다:

```typescript
    /** 이 턴에 실제로 낸 매매 비용. 요율을 못 받았으면 null(측정 불가). */
    fees: number | null;
    /** 턴이 열린 시각. 구 기록에는 없을 수 있다. */
    startedAt: string | null;
```

`summarizeTurn`을 교체:

```typescript
export function summarizeTurn(args: {
    turn: ProgramTurn | null;
    lastTurn: LastTurnResult | null;
    positions: Record<string, ProgramPosition>;
    prices: Record<string, number>;
    programEnabled: boolean;
    feeRates?: FeeRates;
}): TurnSummary {
    const live = args.turn ? computeTurnPnl(args.turn, args.positions, args.prices, args.feeRates) : null;
    const isLive = args.programEnabled && !!args.turn;
    const capital = args.turn?.capital ?? args.lastTurn?.capital ?? 0;
    const pnl = live ? live.pnl : (args.lastTurn?.pnl ?? 0);
    const byTag = live ? live.byTag : (args.lastTurn?.by_tag ?? {});
    const fees = live ? live.fees : (args.lastTurn?.fees ?? null);

    return {
        has: !!args.turn || !!args.lastTurn,
        isLive,
        capital,
        measurable: (isLive || args.lastTurn?.pnl != null) && capital > 0,
        pendingFirstRun: isLive && args.turn?.active_tag == null,
        pnl,
        ratePct: capital > 0 ? (pnl / capital) * 100 : 0,
        byTag,
        fees,
        startedAt: (args.turn as any)?.started_at ?? args.lastTurn?.started_at ?? null,
        tagRows: Object.entries(byTag).filter(([, v]) => v !== 0).sort((a, b) => b[1] - a[1]),
    };
}
```

`ProgramTurn` 타입에 `started_at?: string;`을 더한다. import에 `FeeRates`를 추가한다.

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test "src/**/*.test.ts"`
Expected: PASS. `npx tsc --noEmit`은 아직 `TradeClient.tsx`에서 에러가 난다(Task 8에서 고친다).

- [ ] **Step 5: Commit**

```bash
git add src/lib/real-account-summary.ts src/lib/real-account-summary.test.ts src/lib/program-turn.ts
git commit -m "feat(trade): 화면 요약값을 턴 기준으로 재정의한다"
```

---

### Task 8: 화면 재구성

**Files:**
- Modify: `src/app/trade/useProgramTrading.ts` (상태 30-38행, `fetchProgram` 40-60행, 반환 99-108행)
- Modify: `src/app/api/trade/program/route.ts` (GET 응답에서 `kis_realized_pnl` 제거, `fee_rates` 추가)
- Modify: `src/app/trade/TradeClient.tsx` (`renderRealPortfolioSection` 350-560행)

**Interfaces:**
- Consumes: `summarizeProgram`·`summarizeTurn`(Task 7), `turn_history`(Task 5)

- [ ] **Step 1: 라우트 응답 정리**

`src/app/api/trade/program/route.ts`:
- `kisRealized` IIFE(245-259행)와 `kis_realized_pnl` 응답 필드를 **삭제**한다. `getRealizedProfitBuckets` import도 이제 이 파일에서 안 쓰면 함께 지운다(다른 소비자가 있으면 남긴다).
- `pnl_since`는 남긴다 — ⓑ 대사기가 쓴다.
- `getPositions`의 반환과 GET 응답에 `fee_rates`를 더한다:

```typescript
            fee_rates: content.fee_rates && typeof content.fee_rates === 'object'
                ? content.fee_rates : null,   // 원장에 아직 없으면 null → 화면은 '측정 불가'
```

(`getPositions`의 `empty`에도 `fee_rates: null`을 넣고, 성공 경로에서 `content.fee_rates`를 읽어 반환한다.)

- [ ] **Step 2: 훅 정리**

`src/app/trade/useProgramTrading.ts`:
- `programKisRealized`·`setProgramKisRealized` 상태와 `fetchProgram`의 해당 줄, 반환값에서의 노출을 **삭제**한다
- `programFeeRates`(`FeeRates | undefined`)와 `programTurnHistory`(`LastTurnResult[]`) 상태를 추가하고, `fetchProgram`에서 채운 뒤 반환에 더한다:

```typescript
            setProgramFeeRates(d.fee_rates ?? undefined);
            setProgramTurnHistory(Array.isArray(d.turn_history) ? d.turn_history : []);
```

- `programPnlSince`는 남긴다(ⓑ에서 쓴다).

- [ ] **Step 3: 화면 교체**

`src/app/trade/TradeClient.tsx`의 `summarizeProgram`/`summarizeTurn` 호출을 새 시그니처로 바꾼다:

```typescript
        const program = summarizeProgram({ positions: programPositions, prices: priceMap });
        const turn = summarizeTurn({
            turn: programTurn,
            lastTurn: programLastTurn,
            positions: programPositions,
            prices: priceMap,
            programEnabled,
            feeRates: programFeeRates,
        });
```

`프로그램 매매` `<Divider>` 아래의 `<SimpleGrid cols={{ base: 2, sm: 4 }}>` 블록(471-534행)을 통째로 교체한다. 4칸은 **수익률 / 평가손익(net) / 보유 종목 총액 / 원금**이다:

```tsx
                            <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="md" mb="md">
                                <Stack gap={2}>
                                    <Text size="xs" c="dimmed">수익률</Text>
                                    {!turn.has ? (
                                        <Text size="sm" c="dimmed" mt={4}>턴 없음 — 껐다 켜면 시작</Text>
                                    ) : !turn.measurable ? (
                                        <Text fw={800} size="lg" c="dimmed">측정 불가</Text>
                                    ) : (
                                        <Text fw={800} size="lg" c={turn.pnl >= 0 ? 'red' : 'blue'}>
                                            {turn.pnl >= 0 ? '+' : ''}{turn.ratePct.toFixed(2)}%
                                        </Text>
                                    )}
                                </Stack>
                                <Stack gap={2}>
                                    <Text size="xs" c="dimmed">평가손익 (net)</Text>
                                    {turn.has && turn.measurable ? (
                                        <>
                                            <Text fw={700} size="lg" c={turn.pnl >= 0 ? 'red' : 'blue'}>
                                                {turn.pnl >= 0 ? '+' : ''}{Math.round(turn.pnl).toLocaleString()} 원
                                            </Text>
                                            <Text size="xs" c="dimmed">
                                                {turn.fees === null
                                                    ? '수수료 측정 불가'
                                                    : `수수료 ${Math.round(turn.fees).toLocaleString()}원 차감`}
                                            </Text>
                                        </>
                                    ) : (
                                        <Text fw={700} size="lg" c="dimmed">측정 불가</Text>
                                    )}
                                </Stack>
                                <Stack gap={2}>
                                    <Text size="xs" c="dimmed">보유 종목 총액</Text>
                                    {programLedgerOk ? (
                                        <Text fw={700} size="lg">{Math.round(program.holdingsValue).toLocaleString()} 원</Text>
                                    ) : (
                                        <Text fw={700} size="lg" c="dimmed">측정 불가</Text>
                                    )}
                                </Stack>
                                <Stack gap={2}>
                                    <Text size="xs" c="dimmed">원금</Text>
                                    {turn.capital > 0 ? (
                                        <Text fw={700} size="lg">{Math.round(turn.capital).toLocaleString()} 원</Text>
                                    ) : (
                                        <Text fw={700} size="lg" c="dimmed">측정 불가</Text>
                                    )}
                                </Stack>
                            </SimpleGrid>
```

`<Divider>`의 label을 현재 턴 표시로 바꾼다:

```tsx
                            <Divider mb="sm" labelPosition="left" label={
                                turn.startedAt
                                    ? `프로그램 매매 · 현재 턴 ${turn.startedAt.slice(5, 16).replace('T', ' ')} ~ ${turn.isLive ? '진행 중' : '종료'}`
                                    : '프로그램 매매'
                            } />
```

`턴당 SIM별 수익률` 블록(537-560행)의 라벨만 `전략별 기여도 (합계 = 수익률)`로 바꾸고 나머지는 그대로 둔다.

그 블록 **아래**에 지난 턴 목록을 추가한다:

```tsx
                    {programTurnHistory.length > 0 && (
                        <Stack gap={4} mb="md">
                            <Text size="xs" c="dimmed">지난 턴</Text>
                            {programTurnHistory.map((t) => (
                                <Text key={t.id} size="xs" c="dimmed">
                                    {(t.started_at ?? '?').slice(5, 16).replace('T', ' ')} ~ {t.ended_at.slice(5, 16).replace('T', ' ')}
                                    {' · 원금 '}{Math.round(t.capital).toLocaleString()}원
                                    {' · '}
                                    {t.pnl === null
                                        ? '측정 불가'
                                        : `${t.pnl >= 0 ? '+' : ''}${Math.round(t.pnl).toLocaleString()}원 (${t.capital > 0 ? ((t.pnl / t.capital) * 100).toFixed(2) : '-'}%)`}
                                    {t.fees != null && ` · 수수료 ${Math.round(t.fees).toLocaleString()}원`}
                                </Text>
                            ))}
                        </Stack>
                    )}
```

`programKisRealized`·`programPnlSince`를 쓰던 구조분해(110-112행)와 `KIS 실측 실현손익` 칸은 이미 위 교체로 사라졌다. `programPnlSince`는 아직 안 쓰므로 구조분해에서 뺀다.

- [ ] **Step 4: 타입체크와 테스트**

Run: `npx tsc --noEmit` 그리고 `node --test "src/**/*.test.ts"` 그리고 `python -m pytest tests/ -q`
Expected: 전부 PASS, 타입 에러 0

- [ ] **Step 5: Commit**

```bash
git add src/app/trade/TradeClient.tsx src/app/trade/useProgramTrading.ts src/app/api/trade/program/route.ts
git commit -m "feat(trade): 프로그램 매매 화면을 턴 기준으로 바꾼다"
```

---

## 배포 후 확인

1. 프로그램 매매를 **껐다 켠다** → `수익률`·`평가손익(net)`·`원금`이 새 턴 기준으로 뜨는지
2. 파이썬이 한 사이클 돈 뒤 → `수수료 N원 차감`이 "측정 불가"에서 숫자로 바뀌는지(`fee_rates`가 원장에 찍혀야 한다)
3. 파이썬 첫 런 **전후로 수익률이 점프하지 않는지** — Task 4가 고친 것
4. 다시 껐다 켠다 → `지난 턴`에 방금 턴이 한 줄 쌓이는지
5. `전략별 기여도`의 합계가 `수익률`과 같은지

## 다음 계획

ⓑ 대사기(`turn.fills[]` + `reconcile_fills` + 경고 배너 + 텔레그램)는 별도 계획으로 쓴다. 이 계획의 `pnl_since`·`fee_rates`·`turn.fees_realized`를 그대로 쓴다.
