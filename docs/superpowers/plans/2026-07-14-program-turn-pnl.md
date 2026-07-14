# 실전 계좌 정보창 확장 (보유 총액 · 턴당 수익률 · SIM별 기여도) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/trade` 실전 계좌 카드에 보유 종목 총액 · 프로그램 보유 종목 총액 · 프로그램 턴당 수익률 · 턴당 SIM별 기여도 4개 지표를 추가한다.

**Architecture:** 기존 `realized_pnl`(평단 기준, 복리 계산용)은 손대지 않고, **기준가(basis) 기준의 턴 회계**를 별도 트랙으로 신설한다. 기준가는 턴 시작·전략 스위칭 시점에 그 순간 시세로 리셋된다(MTM). 기록은 파이썬(원장 = 유일 writer), 표시 계산은 TypeScript(route + 프론트 공용 헬퍼)가 담당한다.

**Tech Stack:** Python 3.11 (pytest), Next.js 14 App Router, TypeScript, Mantine UI

## Global Constraints

- **턴 회계는 표시 전용이다.** `realized_pnl` · `effective_budget` · 주문 집행 로직 · 안전 게이트는 **일절 변경하지 않는다**.
- 파이썬 쪽 턴 회계 코드는 **모든 예외를 삼킨다.** 회계 버그가 실주문 경로를 절대 막아선 안 된다(진흥기업 5연속 매수 사고 재발 방지 원칙).
- OFF(kill-switch)는 **무조건 성공해야 한다.** 턴 동결 계산이 실패해도 `enabled: false` 기록은 진행한다.
- 단일 writer 불변식 유지: `program_trading.json`은 프론트 route만, `program_positions.json`은 `program_trader.py`만 쓴다.
- 태그(tag)는 manifest의 실제 심 id를 쓴다: `sim10_orchestrator`, `sim4_bull_daytrading`(BULL), `sim5_sideways`(SIDEWAYS), `cash`(BEAR).
- 스펙: `docs/superpowers/specs/2026-07-14-program-turn-pnl-design.md`

---

## File Structure

| 파일 | 책임 |
|---|---|
| `src/pipeline/workers/program_turn.py` (신규) | 턴 회계 **순수 함수** — I/O 없음. 원장 dict을 받아 갱신. |
| `tests/test_program_turn.py` (신규) | 위 순수 함수의 단위 테스트. |
| `src/pipeline/workers/program_trader.py` (수정) | 순수 함수를 매매 흐름에 끼워넣기. 태그 결정. |
| `src/lib/program-turn.ts` (신규) | 턴 손익 **표시 계산** — route와 프론트가 공유. |
| `src/app/api/trade/program/route.ts` (수정) | ON=턴 열기, OFF=동결, GET=노출. |
| `src/app/trade/TradeClient.tsx` (수정) | 지표 4개 표시. |

기록(파이썬)과 표시 계산(TS)이 언어가 갈리므로 손익 계산식이 양쪽에 존재한다. 파이썬은 **기록만**(`record_sell`이 확정 손익을 `by_tag`에 적립), TS는 **표시만**(`by_tag` + 보유분 미실현) 담당해 중복을 최소화한다.

---

### Task 1: 턴 회계 순수 함수 + 단위 테스트

**Files:**
- Create: `src/pipeline/workers/program_turn.py`
- Test: `tests/test_program_turn.py`

**Interfaces:**
- Consumes: 없음 (순수 함수, 외부 의존 없음)
- Produces:
  - `new_turn(turn_id: str, capital: float, positions: dict, opening_basis: dict | None, current_prices: dict | None) -> dict`
  - `switch_tag(turn: dict, positions: dict, new_tag: str, current_prices: dict) -> None` (turn과 positions를 제자리 변경)
  - `record_buy(turn: dict, code: str, qty: int, price: float, prev_qty: int) -> None`
  - `record_sell(turn: dict, code: str, qty: int, price: float) -> None`
  - `prune_basis(turn: dict, positions: dict) -> None`
  - turn dict 형태: `{"id": str, "capital": float, "basis": {code: price}, "by_tag": {tag: pnl}, "active_tag": str | None}`

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/test_program_turn.py`:

```python
"""프로그램 매매 턴 회계 순수 함수 테스트.

턴 = 프로그램 ON부터 OFF까지. 기준가(basis)는 턴 시작·스위칭 시점에 MTM 리셋된다.
핵심 불변식: 모든 턴의 손익 합 = 평단 기준 누적 실현손익.
"""

from src.pipeline.workers.program_turn import (
    new_turn, switch_tag, record_buy, record_sell, prune_basis,
)


def _pos(qty, avg, tag=None):
    p = {"name": "테스트", "quantity": qty, "avg_price": avg}
    if tag:
        p["tag"] = tag
    return p


def test_new_turn_uses_opening_basis_over_current_price():
    """ON 시점 스냅샷(opening_basis)이 있으면 그것을 기준가로 쓴다."""
    positions = {"005930": _pos(10, 3000)}
    turn = new_turn("t1", 1_200_000, positions,
                    opening_basis={"005930": 3500}, current_prices={"005930": 3600})
    assert turn["basis"]["005930"] == 3500
    assert turn["capital"] == 1_200_000
    assert turn["by_tag"] == {}
    assert turn["active_tag"] is None


def test_new_turn_falls_back_to_current_price():
    """opening_basis가 비어 있으면(ON 시 잔고 조회 실패) 현재가로 채운다."""
    positions = {"005930": _pos(10, 3000)}
    turn = new_turn("t1", 1_000_000, positions, opening_basis={}, current_prices={"005930": 3600})
    assert turn["basis"]["005930"] == 3600


def test_first_tag_assignment_keeps_opening_basis():
    """턴 첫 실행(active_tag=None)은 기준가를 덮어쓰지 않는다.

    ON 시점(3500)부터 첫 실행(3600) 사이의 변동은 첫 태그의 몫이어야 한다.
    여기서 기준가를 3600으로 리셋하면 그 100원이 어느 턴에도 안 잡힌다.
    """
    positions = {"005930": _pos(10, 3000)}
    turn = new_turn("t1", 1_000_000, positions, {"005930": 3500}, {})
    switch_tag(turn, positions, "sim4_bull_daytrading", {"005930": 3600})
    assert turn["basis"]["005930"] == 3500          # 리셋되지 않음
    assert turn["active_tag"] == "sim4_bull_daytrading"
    assert positions["005930"]["tag"] == "sim4_bull_daytrading"
    assert turn["by_tag"] == {}                      # 락인할 직전 태그가 없음


def test_switch_locks_in_previous_tag_and_resets_basis():
    """스위칭 시 직전 태그가 자기 구간의 평가손익을 확정 귀속받고, 기준가가 리셋된다."""
    positions = {"005930": _pos(10, 3000, tag="sim4_bull_daytrading")}
    turn = {"id": "t1", "capital": 1_000_000, "basis": {"005930": 3000},
            "by_tag": {}, "active_tag": "sim4_bull_daytrading"}

    switch_tag(turn, positions, "sim5_sideways", {"005930": 3500})

    assert turn["by_tag"]["sim4_bull_daytrading"] == 5000.0   # (3500-3000)*10
    assert turn["basis"]["005930"] == 3500
    assert turn["active_tag"] == "sim5_sideways"
    assert positions["005930"]["tag"] == "sim5_sideways"


def test_switch_to_same_tag_is_noop():
    positions = {"005930": _pos(10, 3000, tag="sim5_sideways")}
    turn = {"id": "t1", "capital": 1_000_000, "basis": {"005930": 3000},
            "by_tag": {}, "active_tag": "sim5_sideways"}
    switch_tag(turn, positions, "sim5_sideways", {"005930": 3500})
    assert turn["by_tag"] == {}
    assert turn["basis"]["005930"] == 3000


def test_switch_without_price_keeps_position_on_old_tag():
    """시세가 없으면 락인할 수 없다 — 그 종목은 직전 태그·기준가를 유지한다."""
    positions = {"005930": _pos(10, 3000, tag="sim4_bull_daytrading")}
    turn = {"id": "t1", "capital": 1_000_000, "basis": {"005930": 3000},
            "by_tag": {}, "active_tag": "sim4_bull_daytrading"}
    switch_tag(turn, positions, "sim5_sideways", {})     # 시세 없음
    assert positions["005930"]["tag"] == "sim4_bull_daytrading"
    assert turn["basis"]["005930"] == 3000
    assert turn["active_tag"] == "sim5_sideways"


def test_record_buy_sets_basis_to_fill_price():
    turn = {"id": "t1", "capital": 1_000_000, "basis": {}, "by_tag": {}, "active_tag": "sim5_sideways"}
    record_buy(turn, "005930", qty=10, price=3000, prev_qty=0)
    assert turn["basis"]["005930"] == 3000.0


def test_record_buy_weights_basis_on_add_on():
    """추가 매수 시 기준가는 평단처럼 가중평균된다."""
    turn = {"id": "t1", "capital": 1_000_000, "basis": {"005930": 1000},
            "by_tag": {}, "active_tag": "sim5_sideways"}
    record_buy(turn, "005930", qty=10, price=1200, prev_qty=10)
    assert turn["basis"]["005930"] == 1100.0     # (1000*10 + 1200*10) / 20


def test_record_sell_credits_active_tag_against_basis():
    """매도 손익은 평단이 아니라 기준가 대비로 활성 태그에 귀속된다."""
    turn = {"id": "t2", "capital": 1_000_000, "basis": {"005930": 3500},
            "by_tag": {}, "active_tag": "sim5_sideways"}
    record_sell(turn, "005930", qty=10, price=3700)
    assert turn["by_tag"]["sim5_sideways"] == 2000.0    # (3700-3500)*10


def test_prune_basis_drops_sold_out_codes():
    turn = {"id": "t1", "capital": 1_000_000, "basis": {"005930": 3500, "000660": 1000},
            "by_tag": {}, "active_tag": "sim5_sideways"}
    prune_basis(turn, {"000660": _pos(5, 1000)})
    assert "005930" not in turn["basis"]
    assert "000660" in turn["basis"]


def test_turn_pnl_sum_equals_cumulative_realized_pnl():
    """핵심 불변식: 턴별 손익의 합 = 평단 기준 누적 실현손익.

    턴1(sim4): 3000에 10주 매수 → OFF 시점 3500 (미실현 +5000, 턴1 몫으로 동결)
    턴2(sim5): 기준가 3500으로 리셋 → 3700에 전량 매도 (턴2 몫 +2000)
    평단 기준 누적 실현손익 = (3700-3000)*10 = +7000 = 5000 + 2000
    """
    positions = {"005930": _pos(10, 3000)}

    # ── 턴1: 매수 후 미실현 상태로 OFF
    turn1 = new_turn("t1", 1_000_000, {}, {}, {})
    switch_tag(turn1, {}, "sim4_bull_daytrading", {})
    record_buy(turn1, "005930", qty=10, price=3000, prev_qty=0)
    positions["005930"]["tag"] = "sim4_bull_daytrading"
    # OFF 시점 동결(TS의 computeTurnPnl과 동일한 계산): by_tag + 보유분 미실현
    off_price = 3500
    turn1_pnl = sum(turn1["by_tag"].values()) + (off_price - turn1["basis"]["005930"]) * 10
    assert turn1_pnl == 5000

    # ── 턴2: 기준가가 OFF 시점 시세로 리셋되어 시작
    turn2 = new_turn("t2", 1_005_000, positions,
                     opening_basis={"005930": off_price}, current_prices={})
    switch_tag(turn2, positions, "sim5_sideways", {"005930": off_price})
    record_sell(turn2, "005930", qty=10, price=3700)
    del positions["005930"]
    prune_basis(turn2, positions)
    turn2_pnl = sum(turn2["by_tag"].values())
    assert turn2_pnl == 2000
    assert turn2["by_tag"]["sim5_sideways"] == 2000

    # ── 불변식
    cumulative_realized = (3700 - 3000) * 10      # program_trader의 realized_pnl 계산식
    assert turn1_pnl + turn2_pnl == cumulative_realized == 7000
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_program_turn.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.pipeline.workers.program_turn'`

- [ ] **Step 3: 순수 함수를 구현한다**

`src/pipeline/workers/program_turn.py` (신규):

```python
"""프로그램 매매 턴 회계 (표시 전용, 순수 함수)
=======================================================
턴 = 프로그램 매매를 켠 시점부터 끈 시점까지.

기존 원장의 realized_pnl은 평단(avg_price) 기준으로 누적되며 effective_budget(복리)의
근거다 — 여기에는 절대 손대지 않는다. 턴 회계는 그와 분리된 별도 트랙으로, 기준가(basis)
기준으로 집계한다. 기준가는 턴 시작·전략 스위칭 시점에 그 순간 시세로 리셋된다(MTM).

이렇게 하면 이전 턴이 만든 미실현 이익이 새 턴 성과로 둔갑하지 않고, 턴별 손익의 합은
평단 기준 누적 실현손익과 정확히 일치한다.

이 모듈은 I/O를 하지 않는다. 원장 dict을 받아 제자리에서 갱신할 뿐이다.
"""

# Sim10의 국면 → 하위 전략 태그 (manifest의 실제 심 id)
REGIME_TAG = {
    'BULL': 'sim4_bull_daytrading',
    'SIDEWAYS': 'sim5_sideways',
    'BEAR': 'cash',
}


def new_turn(turn_id: str, capital: float, positions: dict,
             opening_basis: dict | None = None, current_prices: dict | None = None) -> dict:
    """새 턴을 연다. 물려받은 보유 종목의 기준가를 턴 시작 시세로 재설정한다(MTM).

    기준가 우선순위: opening_basis(프론트가 ON 시점에 찍은 스냅샷) > current_prices > 평단.
    """
    opening_basis = opening_basis or {}
    current_prices = current_prices or {}
    basis = {}
    for code, p in positions.items():
        px = opening_basis.get(code) or current_prices.get(code) or p.get('avg_price', 0)
        basis[code] = float(px)
    return {'id': turn_id, 'capital': float(capital), 'basis': basis,
            'by_tag': {}, 'active_tag': None}


def switch_tag(turn: dict, positions: dict, new_tag: str, current_prices: dict) -> None:
    """활성 전략을 전환한다. 직전 태그가 자기 구간의 평가손익을 확정 귀속받고, 기준가가 리셋된다.

    턴 첫 실행(active_tag=None)은 락인할 직전 태그가 없으므로 기준가를 그대로 둔다 —
    ON 시점부터 첫 실행까지의 변동은 첫 태그의 몫이다.
    """
    old = turn.get('active_tag')
    if old == new_tag:
        return
    basis = turn.setdefault('basis', {})
    by_tag = turn.setdefault('by_tag', {})
    for code, p in positions.items():
        if old is None:
            p['tag'] = new_tag           # 기준가는 new_turn이 잡은 ON 시점 값 유지
            continue
        px = float(current_prices.get(code) or 0)
        if px <= 0:
            continue                     # 시세 없음 → 락인 불가. 이 종목은 직전 태그·기준가 유지.
        b = float(basis.get(code, px))
        by_tag[old] = round(by_tag.get(old, 0.0) + (px - b) * p['quantity'], 2)
        basis[code] = px
        p['tag'] = new_tag
    turn['active_tag'] = new_tag


def record_buy(turn: dict, code: str, qty: int, price: float, prev_qty: int) -> None:
    """매수 체결 반영. 추가 매수 시 기준가는 평단처럼 가중평균된다.

    prev_qty는 체결 반영 '이전'의 보유 수량이다(호출부가 _apply_order_to_positions 전에 캡처).
    """
    basis = turn.setdefault('basis', {})
    price = float(price)
    if prev_qty > 0 and code in basis:
        basis[code] = (basis[code] * prev_qty + price * qty) / (prev_qty + qty)
    else:
        basis[code] = price


def record_sell(turn: dict, code: str, qty: int, price: float) -> None:
    """매도 체결 반영. 평단이 아니라 '기준가' 대비 손익을 활성 태그에 귀속한다."""
    tag = turn.get('active_tag')
    basis = turn.get('basis', {})
    if not tag or code not in basis:
        return
    by_tag = turn.setdefault('by_tag', {})
    by_tag[tag] = round(by_tag.get(tag, 0.0) + (float(price) - basis[code]) * qty, 2)


def prune_basis(turn: dict, positions: dict) -> None:
    """전량 매도된 종목의 기준가를 정리한다(손익은 record_sell이 이미 귀속시켰다)."""
    basis = turn.get('basis', {})
    for code in list(basis):
        if code not in positions:
            basis.pop(code, None)
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_program_turn.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/pipeline/workers/program_turn.py tests/test_program_turn.py
git commit -m "feat(program): 턴 회계 순수 함수 + 단위 테스트

기준가(basis) 기준 MTM 트랙. 턴 시작·스위칭 시 리셋.
기존 realized_pnl(평단 기준, 복리용)과 완전 분리 — 표시 전용."
```

---

### Task 2: program_trader에 턴 회계 통합

**Files:**
- Modify: `src/pipeline/workers/program_trader.py`
- Test: `tests/test_program_turn.py` (태그 결정 테스트 추가)

**Interfaces:**
- Consumes: Task 1의 `new_turn`, `switch_tag`, `record_buy`, `record_sell`, `prune_basis`, `REGIME_TAG`
- Produces:
  - `_resolve_active_tag(sim_id: str, snapshot: dict) -> str`
  - 원장에 `turn` 키와 `positions[code]["tag"]`가 기록된다.

- [ ] **Step 1: 태그 결정 함수의 실패하는 테스트를 작성한다**

`tests/test_program_turn.py` 파일 **끝에 추가**:

```python
# ── 활성 태그 결정 (program_trader) ──────────────────────────────────
from src.pipeline.workers.program_trader import _resolve_active_tag


def test_normal_sim_tag_is_sim_id():
    """일반 심은 자기 id가 곧 태그다 — 턴 안에서 바뀌지 않는다."""
    assert _resolve_active_tag("sim5_sideways", {}) == "sim5_sideways"
    assert _resolve_active_tag("sim7_report_follower", {"active_regime": "BULL"}) == "sim7_report_follower"


def test_sim10_tag_follows_active_regime():
    """Sim10만 하위 전략으로 분해된다. active_regime은 Sim10이 run() 중 스냅샷에 쓴 값."""
    assert _resolve_active_tag("sim10_orchestrator", {"active_regime": "BULL"}) == "sim4_bull_daytrading"
    assert _resolve_active_tag("sim10_orchestrator", {"active_regime": "SIDEWAYS"}) == "sim5_sideways"
    assert _resolve_active_tag("sim10_orchestrator", {"active_regime": "BEAR"}) == "cash"


def test_sim10_unknown_regime_falls_back_to_sim_id():
    """국면을 못 읽었으면(스냅샷 오염 등) 심 id로 폴백 — 손익이 유실되지 않는다."""
    assert _resolve_active_tag("sim10_orchestrator", {}) == "sim10_orchestrator"
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_program_turn.py -v`
Expected: FAIL (collection error) — `ImportError: cannot import name '_resolve_active_tag' from 'src.pipeline.workers.program_trader'`

- [ ] **Step 3: import와 태그 결정 함수를 추가한다**

`src/pipeline/workers/program_trader.py` — 상단 import 블록(`from datetime import datetime, timedelta` 다음 줄)에 추가:

```python
from src.pipeline.workers.program_turn import (
    REGIME_TAG, new_turn, switch_tag, record_buy, record_sell, prune_basis,
)
```

같은 파일, `_recently_ran` 함수 **바로 위**에 추가:

```python
def _resolve_active_tag(sim_id: str, snapshot: dict) -> str:
    """턴 회계용 활성 전략 태그.

    Sim10은 Sim0 국면에 따라 하위 전략(Sim4-1/Sim5/현금)을 갈아타므로 그 하위 전략을
    태그로 쓴다. active_regime은 Sim10이 run() 중 self.state(=스냅샷)에 써둔 값이라
    Sim10을 수정하지 않고 읽기만 하면 된다. 나머지 심은 자기 id가 곧 태그다.
    """
    if sim_id != 'sim10_orchestrator':
        return sim_id
    return REGIME_TAG.get(snapshot.get('active_regime'), sim_id)
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_program_turn.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: 기본 원장에 turn 슬롯을 추가한다**

`src/pipeline/workers/program_trader.py:77-78`의 `_default_ledger`를 교체:

```python
def _default_ledger() -> dict:
    return {'positions': {}, 'last_run': None, 'sim': None, 'realized_pnl': 0,
            'cooldown_codes': {}, 'turn': {}}
```

`_read_ledger_fresh` 안의 `d.setdefault('cooldown_codes', {})` **다음 줄**에 추가 (기존 원장에 turn이 없어도 안전하게):

```python
        d.setdefault('turn', {})
```

- [ ] **Step 6: 턴 열기 — 현재가 맵 구성 직후에 끼워넣는다**

`run_program_trading` 안, 기존 8번 주석(`# 8. 실계좌 스냅샷 state 구성 ...`) **바로 위**에 추가한다. 이 위치인 이유: `positions`와 `current_prices`가 모두 준비된 첫 지점이기 때문이다.

```python
    # 7-b. [턴 회계] config가 연 턴을 원장에 반영. 표시 전용 — 실패해도 매매는 계속한다.
    turn = ledger.get('turn') or {}
    try:
        cfg_turn = cfg.get('turn') or {}
        if cfg_turn.get('id') and turn.get('id') != cfg_turn['id']:
            turn = new_turn(
                cfg_turn['id'],
                cfg_turn.get('capital') or effective_budget,
                positions,
                cfg_turn.get('opening_basis'),
                current_prices,
            )
            log(f"[Program] 새 턴 시작: {cfg_turn['id']} (자본 {turn['capital']:,.0f})")
    except Exception as e:
        log_error(f'[Program] 턴 열기 실패(무시): {e}')
        turn = {}
```

- [ ] **Step 7: 활성 태그 전환 — sim.run() 직후에 끼워넣는다**

같은 함수, `sim.run(...)`을 감싼 try/except 블록 **바로 다음**(기존 `if not orders:` 앞)에 추가:

```python
    # [턴 회계] 활성 전략 확정. Sim10이면 이번 run의 국면(하위 전략)이 스냅샷에 들어있다.
    # 전략이 바뀌었으면 직전 전략의 평가손익을 락인하고 기준가를 리셋한다(MTM).
    active_tag = sim_id
    try:
        active_tag = _resolve_active_tag(sim_id, snapshot)
        if turn:
            switch_tag(turn, positions, active_tag, current_prices)
    except Exception as e:
        log_error(f'[Program] 턴 태그 전환 실패(무시): {e}')
```

- [ ] **Step 8: 주문 없음 경로에서도 턴을 저장한다**

같은 함수의 `if not orders:` 블록에서 `ledger['sim'] = sim_id` **다음 줄**에 추가:

```python
        ledger['turn'] = turn
```

- [ ] **Step 9: 체결 반영 시 턴 회계를 기록한다**

주문 루프 안, 기존 `if res.get('success'):` 블록을 교체한다. **기존 realized_pnl 누적(평단 기준)은 그대로 두고**, 턴 회계만 덧붙인다:

```python
            if res.get('success'):
                # [복리] 매도 체결분의 실현손익을 원장에 누적(다음 실행의 effective_budget에 반영).
                # _apply_order_to_positions가 positions[code]를 지우거나 수량을 줄이기 전에 계산해야 함.
                # price는 KIS 확정 체결가가 아닌 주문가 추정치 — 원장의 avg_price/peak_price와 동일한
                # 근사 정밀도(기존 설계와 일관).
                if side == 'sell' and code in positions:
                    realized_delta = qty * (price - positions[code]['avg_price'])
                    ledger['realized_pnl'] = round(ledger.get('realized_pnl', 0) + realized_delta, 2)
                # [턴 회계] 표시 전용 별도 트랙(기준가 대비). 실패해도 매매·원장은 계속한다.
                prev_qty = positions.get(code, {}).get('quantity', 0)
                try:
                    if turn:
                        if side == 'sell':
                            record_sell(turn, code, qty, price)
                        else:
                            record_buy(turn, code, qty, price, prev_qty)
                except Exception as e:
                    log_error(f'[Program] 턴 체결 기록 실패(무시): {e}')
                _apply_order_to_positions(positions, o, today)
                if turn and side == 'buy' and code in positions:
                    positions[code]['tag'] = active_tag
                append_order_history({
                    'executed_at': now_kst.isoformat(), 'side': side, 'code': code,
                    'name': o.get('name', ''), 'qty': qty, 'price': price,
                    'status': 'executed', 'reason': f"[프로그램:{sim_id}] {o.get('reason', '')}",
                })
                executed += 1
                log(f"[Program] 체결: {side.upper()} {code} {qty}주 @ {price}")
```

- [ ] **Step 10: 최종 원장 저장에 턴을 포함한다**

같은 함수 끝(11번 블록), `ledger['sim'] = sim_id` **다음 줄**에 추가:

```python
    try:
        if turn:
            prune_basis(turn, positions)
    except Exception as e:
        log_error(f'[Program] 턴 기준가 정리 실패(무시): {e}')
    ledger['turn'] = turn
```

- [ ] **Step 11: 전체 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/ -q`
Expected: PASS — 기존 테스트 전부 green (턴 회계는 기존 경로를 바꾸지 않았으므로 회귀 없어야 함)

Run: `python -c "from src.pipeline.workers import program_trader; print('import ok')"`
Expected: `import ok`

- [ ] **Step 12: 커밋**

```bash
git add src/pipeline/workers/program_trader.py tests/test_program_turn.py
git commit -m "feat(program): 원장에 턴 회계 기록 + Sim10 하위 전략 태그

턴 전환/스위칭/체결을 원장 turn에 기록. Sim10은 active_regime을 읽어
하위 전략(sim4_bull_daytrading/sim5_sideways/cash)으로 태그 분해.
모든 턴 회계는 예외를 삼켜 주문 경로를 막지 않는다. Sim10 무수정."
```

---

### Task 3: 턴 손익 표시 계산(TS) + API route

**Files:**
- Create: `src/lib/program-turn.ts`
- Modify: `src/app/api/trade/program/route.ts`

**Interfaces:**
- Consumes: Task 2가 원장에 쓴 `turn` · `positions[code].tag`, 기존 `getRealPortfolio()` (`src/lib/kis-api.ts`)
- Produces:
  - `export type ProgramTurn = { id: string; capital: number; basis: Record<string, number>; by_tag: Record<string, number>; active_tag: string | null }`
  - `export type TurnResult = { pnl: number; byTag: Record<string, number> }`
  - `export function computeTurnPnl(turn, positions, prices): TurnResult`
  - GET 응답에 `turn`, `last_turn_result` 추가

- [ ] **Step 1: 표시 계산 헬퍼를 만든다**

`src/lib/program-turn.ts` (신규):

```typescript
/**
 * 프로그램 매매 턴 손익 표시 계산 (route의 OFF 동결 + 프론트 실시간 표시 공용).
 *
 * 기록은 파이썬(program_turn.py)이 원장에 한다. 여기서는 확정분(by_tag)에
 * 현재 보유분의 미실현(현재가 − 기준가)을 얹어 '지금 시점의 턴 손익'을 만든다.
 */

export type ProgramTurn = {
    id: string;
    capital: number;
    basis: Record<string, number>;
    by_tag: Record<string, number>;
    active_tag: string | null;
};

export type ProgramPosition = { name: string; quantity: number; avg_price: number; tag?: string };

export type TurnResult = { pnl: number; byTag: Record<string, number> };

/**
 * 턴 손익 = 확정분(by_tag) + 보유분 미실현(각 종목의 tag에 귀속).
 * 시세를 못 구한 종목은 기여분 0으로 처리한다(기존 프로그램 평가손익 계산과 동일한 폴백).
 */
export function computeTurnPnl(
    turn: ProgramTurn | null | undefined,
    positions: Record<string, ProgramPosition>,
    prices: Record<string, number>,
): TurnResult {
    if (!turn || !turn.id) return { pnl: 0, byTag: {} };

    const byTag: Record<string, number> = { ...(turn.by_tag || {}) };
    const basis = turn.basis || {};

    for (const [code, pos] of Object.entries(positions || {})) {
        const px = Number(prices[code]) || 0;
        if (px <= 0) continue;
        const b = Number(basis[code] ?? px);
        const tag = pos.tag || turn.active_tag || 'unknown';
        byTag[tag] = (byTag[tag] || 0) + (px - b) * pos.quantity;
    }

    const pnl = Object.values(byTag).reduce((s, v) => s + v, 0);
    return { pnl, byTag };
}
```

- [ ] **Step 2: route가 원장의 turn을 읽도록 확장한다**

`src/app/api/trade/program/route.ts` — 상단 import에 추가:

```typescript
import { getRealPortfolio } from '@/lib/kis-api';
import { computeTurnPnl, type ProgramTurn, type ProgramPosition } from '@/lib/program-turn';
```

`getPositions()`(49-73행)를 교체 — `turn`도 함께 반환:

```typescript
async function getPositions(): Promise<{
    positions: Record<string, ProgramPosition>;
    realized_pnl: number;
    turn: ProgramTurn | null;
}> {
    const empty = { positions: {}, realized_pnl: 0, turn: null };
    try {
        const url = `https://api.github.com/repos/${OWNER}/${SECRET_REPO}/contents/${POSITIONS_PATH}?ref=${SECRET_BRANCH}`;
        const res = await fetch(url, {
            headers: { Authorization: `token ${GITHUB_PAT}`, Accept: 'application/vnd.github.v3+json' },
            cache: 'no-store',
        });
        if (!res.ok) return empty; // 404(미실행) 등은 빈 원장으로 취급
        const data = await res.json();
        const content = JSON.parse(Buffer.from(data.content, 'base64').toString('utf-8'));
        return {
            positions: content.positions && typeof content.positions === 'object' ? content.positions : {},
            realized_pnl: Number(content.realized_pnl) || 0,
            turn: content.turn && content.turn.id ? content.turn : null,
        };
    } catch {
        return empty; // 네트워크 실패 등도 non-blocking
    }
}
```

- [ ] **Step 3: 현재가 조회 헬퍼를 추가한다**

`getPositions()` 아래에 추가:

```typescript
/** 프로그램 원장 종목의 현재가 맵. 실패 시 빈 맵(표시 전용이므로 non-blocking). */
async function getLivePrices(): Promise<Record<string, number>> {
    try {
        const p: any = await getRealPortfolio();
        if (p?.error) return {};
        const map: Record<string, number> = {};
        for (const h of p?.holdings || []) {
            if (h?.code) map[h.code] = Number(h.price) || 0;
        }
        return map;
    } catch {
        return {};
    }
}
```

- [ ] **Step 4: GET이 turn과 last_turn_result를 내보내게 한다**

`GET` 안에서 `const { positions, realized_pnl } = await getPositions();`를 교체하고, 응답 객체에 두 필드를 추가:

```typescript
        const { positions, realized_pnl, turn } = await getPositions();
        return NextResponse.json({
            enabled: !!content.enabled,
            selected_sim: content.selected_sim ?? null,
            budget: Number(content.budget) || 0,
            selected_valid: selectedValid,
            updated_at: content.updated_at ?? null,
            sims, // 프론트 드롭다운 재사용
            positions, // 프로그램 원장 포지션(code -> {name, quantity, avg_price, tag})
            realized_pnl, // 프로그램 누적 실현손익(원)
            turn, // 진행 중인 턴(원장) — 프론트가 실시간 손익 계산
            last_turn_result: content.last_turn_result ?? null, // OFF 시 동결된 직전 턴
        });
```

- [ ] **Step 5: OFF에서 턴을 동결한다**

`POST`의 OFF 분기(`if (!wantEnabled) { ... }`)를 교체. **기존 보안 교정(enabled 필드만 변경)은 유지**하고 `last_turn_result`만 덧붙인다:

```typescript
        if (!wantEnabled) {
            const now = new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().replace('T', ' ').split('.')[0];
            // [턴 동결] OFF를 누른 순간의 턴 손익을 박제한다. OFF 이후의 시세 변동은
            // 어느 턴의 성과도 아니므로 섞이지 않는다.
            // 실패해도 OFF(kill-switch)는 무조건 진행한다 — 표시용 계산이 정지를 막아선 안 된다.
            let lastTurnResult: any = content.last_turn_result ?? null;
            try {
                const { positions, turn } = await getPositions();
                const cfgTurn = content.turn;
                if (cfgTurn?.id) {
                    // 원장의 턴 id가 config와 다르면 이번 턴에 파이썬이 한 번도 안 돌았다(장 외 ON→OFF 등).
                    const matched = turn && turn.id === cfgTurn.id ? turn : null;
                    const { pnl, byTag } = matched
                        ? computeTurnPnl(matched, positions, await getLivePrices())
                        : { pnl: 0, byTag: {} };
                    lastTurnResult = {
                        id: cfgTurn.id,
                        ended_at: now,
                        sim: content.selected_sim ?? null,
                        capital: Number(matched?.capital) || Number(cfgTurn.capital) || 0,
                        pnl,
                        by_tag: byTag,
                    };
                }
            } catch (e) {
                console.error('[program] 턴 동결 실패(무시):', e);
            }
            const next = { ...content, enabled: false, updated_at: now,
                updated_by: (token as any).email || (token as any).name || 'user',
                turn: null, last_turn_result: lastTurnResult };
            await putConfig(next, sha, 'program-trading: OFF (kill-switch)');
            return NextResponse.json({ success: true, enabled: false, selected_sim: next.selected_sim, budget: next.budget });
        }
```

- [ ] **Step 6: ON에서 턴을 연다**

`POST`의 ON 분기 끝, `const next = { ... }` 직전에 턴 생성 코드를 넣고 `next`에 `turn`을 포함시킨다:

```typescript
        const now = new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().replace('T', ' ').split('.')[0];

        // [턴 열기] ON 시점의 시세로 물려받은 보유 종목의 기준가를 스냅샷한다(MTM 리셋).
        // 잔고 조회가 실패해도 ON은 정상 진행 — 기준가는 파이썬 첫 실행 때 현재가로 채워진다.
        let turn: any = { id: new Date().toISOString(), started_at: now, capital: budgetNum, opening_basis: {} };
        try {
            const { positions, realized_pnl } = await getPositions();
            turn.capital = budgetNum + realized_pnl;   // 턴 시작 유효자본 = 이 턴에 실제로 굴릴 돈
            const prices = await getLivePrices();
            const basis: Record<string, number> = {};
            for (const code of Object.keys(positions)) {
                const px = Number(prices[code]) || 0;
                if (px > 0) basis[code] = px;
            }
            turn.opening_basis = basis;
        } catch (e) {
            console.error('[program] 턴 열기 스냅샷 실패(기본값으로 진행):', e);
        }

        const next = {
            ...content,
            enabled: true,
            selected_sim: sim,
            budget: budgetNum,
            turn,
            updated_at: now,
            updated_by: (token as any).email || (token as any).name || 'user',
        };
```

기존의 `const now = ...` 한 줄(216행)은 위 블록이 흡수하므로 **중복 선언이 남지 않도록 삭제**한다.

- [ ] **Step 7: 타입 체크**

Run: `npx tsc --noEmit`
Expected: 에러 없음 (0 errors)

- [ ] **Step 8: 커밋**

```bash
git add src/lib/program-turn.ts src/app/api/trade/program/route.ts
git commit -m "feat(program): 턴 열기/동결 API + 표시 계산 헬퍼

ON=현재가로 기준가 스냅샷 후 턴 생성, OFF=그 순간 손익 동결.
둘 다 실패해도 매매 ON/OFF 자체는 진행(표시용 지표가 kill-switch를 막지 않음)."
```

---

### Task 4: 프론트엔드 지표 4종 표시

**Files:**
- Modify: `src/app/trade/TradeClient.tsx`

**Interfaces:**
- Consumes: Task 3의 GET 응답(`turn`, `last_turn_result`, `positions[].tag`), `computeTurnPnl` (`@/lib/program-turn`)
- Produces: 없음 (최종 소비자)

- [ ] **Step 1: 상태와 fetch를 확장한다**

`src/app/trade/TradeClient.tsx` 상단 import에 추가:

```typescript
import { computeTurnPnl, type ProgramTurn } from '@/lib/program-turn';
```

`const [programRealizedPnl, setProgramRealizedPnl] = useState(0);`(95행) **다음 줄**에 추가:

```typescript
    const [programTurn, setProgramTurn] = useState<ProgramTurn | null>(null);
    const [programLastTurn, setProgramLastTurn] = useState<{ capital: number; pnl: number; by_tag: Record<string, number> } | null>(null);
```

또한 `programPositions` state의 타입에 `tag`를 추가한다(94행 교체):

```typescript
    const [programPositions, setProgramPositions] = useState<Record<string, { name: string; quantity: number; avg_price: number; tag?: string }>>({});
```

`fetchProgram` 안, `setProgramRealizedPnl(...)`(216행) **다음 줄**에 추가:

```typescript
            setProgramTurn(d.turn && d.turn.id ? d.turn : null);
            setProgramLastTurn(d.last_turn_result ?? null);
```

- [ ] **Step 2: 렌더 계산을 추가한다**

`renderRealPortfolioSection()` 안, `const programHasData = ...`(533행) **다음 줄**에 추가:

```typescript
        // 프로그램 보유 종목 총액 (원장 포지션 × 실시간 시세)
        const priceMap: Record<string, number> = {};
        for (const h of allHoldings) if (h?.code) priceMap[h.code] = Number(h.price) || 0;
        const programHoldingsValue = Object.entries(programPositions).reduce(
            (sum, [code, pos]) => sum + (priceMap[code] || pos.avg_price) * pos.quantity, 0);

        // 턴 손익: ON이면 원장 turn으로 실시간, OFF면 동결된 직전 턴
        const liveTurn = programTurn ? computeTurnPnl(programTurn, programPositions, priceMap) : null;
        const turnCapital = programTurn?.capital ?? programLastTurn?.capital ?? 0;
        const turnPnl = liveTurn ? liveTurn.pnl : (programLastTurn?.pnl ?? 0);
        const turnByTag = liveTurn ? liveTurn.byTag : (programLastTurn?.by_tag ?? {});
        const turnRate = turnCapital > 0 ? (turnPnl / turnCapital) * 100 : 0;
        const turnIsLive = !!programTurn;
        const hasTurn = !!programTurn || !!programLastTurn;

        // 태그 → 표시명. 하위 전략도 매매 가능 심이라 programSims에 이름이 들어있다.
        const tagLabel = (tag: string) =>
            tag === 'cash' ? '현금(하락장)' : (programSims.find(s => s.id === tag)?.name ?? tag);
        const turnTagRows = Object.entries(turnByTag)
            .filter(([, pnl]) => pnl !== 0)
            .sort((a, b) => b[1] - a[1]);
```

- [ ] **Step 3: 보유 종목 총액을 기존 Group에 추가한다**

기존 3칸 `Group`(580-597행)의 **마지막 Stack 다음, `</Group>` 앞**에 추가:

```tsx
                        <Stack gap={2}>
                            <Text size="xs" c="dimmed">보유 종목 총액</Text>
                            <Text fw={700} size="lg">{Math.round(totalEval).toLocaleString()} 원</Text>
                        </Stack>
```

- [ ] **Step 4: 프로그램 보유 종목 총액을 프로그램 Group에 추가한다**

기존 프로그램 2칸 `Group`(598-613행) 안, 마지막 Stack 다음 **`</Group>` 앞**에 추가:

```tsx
                            <Stack gap={2}>
                                <Text size="xs" c="dimmed">프로그램 매매 보유 종목 총액</Text>
                                <Text fw={700} size="lg">{Math.round(programHoldingsValue).toLocaleString()} 원</Text>
                            </Stack>
```

- [ ] **Step 5: 턴 지표 Group을 추가한다**

프로그램 Group의 닫는 `)}` **다음**, `<Divider mb="xs" label="보유 포트폴리오 ..." />` **앞**에 추가:

```tsx
                    {hasTurn && (
                        <Group grow mb="md" align="flex-start">
                            <Stack gap={2}>
                                <Text size="xs" c="dimmed">
                                    프로그램 매매 턴당 수익률{turnIsLive ? '' : ' (직전 턴)'}
                                </Text>
                                <Text fw={800} size="lg" c={turnPnl >= 0 ? 'red' : 'blue'}>
                                    {turnPnl >= 0 ? '+' : ''}{turnRate.toFixed(2)}%
                                </Text>
                                <Text size="xs" c="dimmed">
                                    {turnPnl >= 0 ? '+' : ''}{Math.round(turnPnl).toLocaleString()} 원 / 원금 {Math.round(turnCapital).toLocaleString()} 원
                                </Text>
                            </Stack>
                            <Stack gap={2}>
                                <Text size="xs" c="dimmed">턴당 SIM별 수익률</Text>
                                {turnTagRows.length === 0 ? (
                                    <Text size="sm" c="dimmed">—</Text>
                                ) : turnTagRows.map(([tag, pnl]) => (
                                    <Group key={tag} gap={6} justify="space-between" wrap="nowrap">
                                        <Text size="sm" truncate>{tagLabel(tag)}</Text>
                                        <Text size="sm" fw={700} c={pnl >= 0 ? 'red' : 'blue'} style={{ whiteSpace: 'nowrap' }}>
                                            {pnl >= 0 ? '+' : ''}{(turnCapital > 0 ? (pnl / turnCapital) * 100 : 0).toFixed(2)}%
                                            {' '}({pnl >= 0 ? '+' : ''}{Math.round(pnl).toLocaleString()})
                                        </Text>
                                    </Group>
                                ))}
                            </Stack>
                        </Group>
                    )}
```

- [ ] **Step 6: 타입 체크**

Run: `npx tsc --noEmit`
Expected: 에러 없음 (0 errors)

- [ ] **Step 7: 빌드 확인**

Run: `npm run build`
Expected: 빌드 성공, `/trade` 라우트 포함

- [ ] **Step 8: 커밋**

```bash
git add src/app/trade/TradeClient.tsx
git commit -m "feat(trade): 보유 총액·프로그램 보유 총액·턴당 수익률·SIM별 기여도 표시

턴 지표는 ON이면 실시간, OFF면 동결된 직전 턴. SIM별은 기여도 분해라
합이 턴 수익률과 일치. 턴 데이터 없으면 블록 자체를 렌더링하지 않는다."
```

---

## 최종 검증 (전체 완료 후)

- [ ] `python -m pytest tests/ -q` — 전부 통과
- [ ] `npx tsc --noEmit` — 0 errors
- [ ] `npm run build` — 성공
- [ ] **기존 원장 호환성**: `turn` 필드가 없는 현 프로덕션 원장 상태에서 GET `/api/trade/program`이 500 없이 응답하고 `turn: null`을 반환하는지. 프론트가 턴 Group을 렌더링하지 않는지.
- [ ] **kill-switch 무결성**: `GITHUB_PAT`를 잘못된 값으로 두고 OFF를 눌러도(= `getPositions`/`getLivePrices` 실패) `enabled: false`가 기록되는지.
- [ ] **회귀**: `realized_pnl` 누적 로직이 턴 회계 도입 전후로 동일한지 (`git diff`로 해당 4줄이 안 바뀌었는지 눈으로 확인).

## 범위 밖

- 턴 히스토리(과거 여러 턴 목록/차트) — 현재 턴 + 직전 턴 하나만 보관.
- 기존 원장 마이그레이션 스크립트 — `turn` 없으면 다음 ON에서 첫 턴이 자연히 열린다.
- Sim10 및 하위 전략 로직 변경 — `active_regime`을 읽기만 한다.
