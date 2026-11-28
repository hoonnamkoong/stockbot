# 가격 이력 계약 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 보유 종목에 가격 이력을 반드시 공급하고, 이력에 날짜를 달아 소비자가 "직전 N일"을 선언하게 하며, 심1·심4의 상수 손절 폴백을 제거한다.

**Architecture:** 날짜 달린 `price_history` 필드 + 공용 판독기 `prior_closes`를 `base_simulator.py`에 둔다. 소비자는 필요한 길이를 인자로 **선언**하고, 못 만들면 `None`을 받아 그 레그만 끈다. 보유 이력은 KIS `get_daily_history`로 받아 `_view()`에 실어 내려보내므로 `run`·`decide_*` 시그니처를 건드리지 않는다.

**Tech Stack:** Python 3.10, pytest, 기존 `src/strategy/simulators/base_simulator.py`·`src/trade/kis_data_provider.py`

**Spec:** [docs/superpowers/specs/2026-11-28-price-history-contract-design.md](../specs/2026-11-28-price-history-contract-design.md)

## Global Constraints

- 조회 실패를 0이나 상수로 채우지 않는다. 측정 불가는 `None`이고, 호출자는 그걸 숫자로 바꾸지 않는다.
- 페이퍼(`trade_engine`)와 실전(`program_trader`)은 **같은 함수**로 이력을 공급한다. 두 곳에 사본을 두지 않는다.
- `MIN_HISTORY = 20`·`TP_ATR_MULT = 3.0`·`SL_ATR_MULT = 1.5`·`MIN_WIDTH_PCT = 8.0`·`LOW_ZONE = 0.03`·`ENTRY_RSI2_MAX = 15.0`·`EXIT_RSI2_MIN = 70.0`·`STOP_PCT = -5.0` — 전략 상수는 **하나도 바꾸지 않는다.**
- 네이버 종가 이력은 **25행**, 수급 계열(외국인·기관 20일 누적, `amount_history`)은 **`rows[:20]`** 에서 만든다.
- 당일 제외는 **청산에만**. 진입은 `prior_closes(…, n-1) + [현재가]`로 당일을 살린다.
- `HISTORY_DAYS = 25`, `PACE_INTERVAL` 기존값(1/10초) 유지.
- 심9-1·심11(EOD)·미국 심·표시용 소비자(`notifier`·`storage_manager`·`analyzer_5days`·`src/app/research/*`·`sim0_libero`)는 **건드리지 않는다.**
- 돈 경로다. 사람 서명 전에 main으로 병합하지 않는다.

## Review Focus

스펙이 함축하지만 어느 태스크 테스트도 건드리지 않는 입력 다섯 가지. 각 줄의 테스트는 해당 태스크에 넣었다.

1. **신규 상장 종목** — 이력이 20일 미만이라 `prior_closes`가 `None`. 기대: 조용한 탈락이 아니라 funnel에 결손 사유로 남는다. → Task 1·6
2. **상장폐지·거래정지 보유 종목** — `get_daily_history`가 빈 리스트. 기대: 공급 dict에 키가 없고, 적응형 레그만 꺼지고 **하드 손절은 난다.** → Task 3·4
3. **긴 연휴(추석·설)** — 25행 요청이 달력상 40일을 벌린다. 기대: 날짜 불연속은 정상이고 거짓 `None`이 아니다. → Task 1
4. **ETF 보유**(심6 `148070`·`357870`) — `get_daily_history`가 ETF에 응답하는지 불확실. 기대: 응답이 없어도 심6는 자기 경로를 쓰므로 영향 없고, 공급 실패가 로그에 남는다. → Task 3
5. **같은 종목이 후보와 보유에 동시에 있을 때** — 두 출처의 이력이 다를 수 있다. 기대: 후보 쪽이 이긴다(규약이 하나여야 한다). → Task 1

---

### Task 1: 날짜 계약 — `prior_closes` · `history_of`

**Files:**
- Modify: `src/strategy/simulators/base_simulator.py` (모듈 수준 함수 추가, `log_funnel` 아래)
- Test: `tests/test_price_history_contract.py` (신규)

**Interfaces:**
- Consumes: 없음
- Produces:
  - `prior_closes(history, today_ymd: str, n: int) -> list[float] | None` — `history`는 `list[{'date': 'YYYYMMDD', 'close': float}]`, 과거→최신. `today_ymd` 행을 뺀 **마지막 n개** 종가를 과거→최신으로. 못 만들면 `None`.
  - `history_of(code, cand_by_code: dict, price_history: dict) -> list[dict] | None` — 후보의 `price_history`를 먼저, 없으면 공급분.
  - `prior_closes_for(code, cand_by_code, view: dict, today_ymd, n) -> list[float] | None` — 위 둘의 합성. `view['price_history']`를 읽는다(없으면 `{}`).
  - `hist_fingerprint(history) -> str` — `'<첫날짜>-<끝날짜>-<길이>-<종가합>'`. `history`가 비면 `''`.

- [ ] **Step 1: Write the failing tests**

```python
H = [{'date': f'202611{d:02d}', 'close': 100.0 + d} for d in (16,17,18,19,20,23,24,25,26,27)]

def test_excludes_today_by_date():
    out = prior_closes(H + [{'date': '20261130', 'close': 999.0}], '20261130', 3)
    assert out == [125.0, 126.0, 127.0]        # 11/25, 11/26, 11/27 — 999는 없다

def test_returns_last_n_not_all():
    assert len(prior_closes(H, '20261130', 5)) == 5
    assert prior_closes(H, '20261130', 5) == [123.0, 124.0, 125.0, 126.0, 127.0]

def test_none_when_shorter_than_n():
    assert prior_closes(H[:3], '20261130', 5) is None   # 패딩하지 않는다

def test_none_when_empty_or_missing():
    assert prior_closes([], '20261130', 1) is None
    assert prior_closes(None, '20261130', 1) is None

def test_drops_nonpositive_close_then_checks_length():
    h = [dict(r) for r in H]; h[0]['close'] = 0
    assert len(prior_closes(h, '20261130', 9)) == 9     # 0 한 행은 버리고 계속
    assert prior_closes(h, '20261130', 10) is None      # 버린 뒤 길이 미달

def test_none_when_any_date_malformed():
    h = [dict(r) for r in H]; h[2]['date'] = '2026-11-18'
    assert prior_closes(h, '20261130', 3) is None       # 날짜는 계약의 근거다

def test_none_when_dates_duplicated():
    h = H + [dict(H[-1])]
    assert prior_closes(h, '20261130', 3) is None

def test_holiday_gap_is_not_an_error():
    """추석 연휴로 9일 비어도 정상이다 — 거짓 None이 적응형 청산을 끈다."""
    h = [{'date': '20261001', 'close': 100.0}, {'date': '20261012', 'close': 101.0},
         {'date': '20261013', 'close': 102.0}]
    assert prior_closes(h, '20261130', 3) == [100.0, 101.0, 102.0]

def test_none_when_unsorted():
    assert prior_closes(list(reversed(H)), '20261130', 3) is None

def test_history_of_prefers_candidate_over_supplied():
    cand = {'A': {'price_history': [{'date': '20261127', 'close': 1.0}]}}
    supplied = {'A': [{'date': '20261127', 'close': 2.0}]}
    assert history_of('A', cand, supplied)[0]['close'] == 1.0

def test_history_of_falls_back_to_supplied():
    assert history_of('A', {}, {'A': [{'date': '20261127', 'close': 2.0}]})[0]['close'] == 2.0

def test_history_of_none_when_neither():
    assert history_of('A', {}, {}) is None

def test_prior_closes_for_reads_view():
    view = {'price_history': {'A': H}}
    assert len(prior_closes_for('A', {}, view, '20261130', 4)) == 4

def test_prior_closes_for_tolerates_view_without_key():
    assert prior_closes_for('A', {}, {}, '20261130', 4) is None

def test_fingerprint_changes_with_window():
    assert hist_fingerprint(H) != hist_fingerprint(H[:-1])
    assert hist_fingerprint([]) == ''
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_price_history_contract.py -q`
Expected: FAIL — `ImportError: cannot import name 'prior_closes'`

- [ ] **Step 3: Implement the four functions in `src/strategy/simulators/base_simulator.py`**

검사 순서가 결과를 정한다: ①날짜 형식(8자리 숫자)·중복·정렬을 먼저 보고 어기면 `None` ②`today_ymd` 행 제거 ③`close <= 0`·`None` 행 제거 ④남은 길이가 `n` 미달이면 `None` ⑤마지막 `n`개 반환. **거래일 연속성은 검사하지 않는다** — 휴장에 거짓 `None`이 나면 적응형 청산이 통째로 꺼진다.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_price_history_contract.py -q`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add tests/test_price_history_contract.py src/strategy/simulators/base_simulator.py
git commit -m "feat: 날짜 달린 가격 이력 판독기 prior_closes"
```

---

### Task 2: 생산자 — 날짜 보존 · 종가 25행 · 수급 20행 고정

**Files:**
- Modify: `src/pipeline/workers/trade_engine.py:725-746` (`fetch_sparkline` 내부)
- Modify: `src/pipeline/workers/data_fetcher.py:325-337` (`_get_stock_details` 내부)
- Test: `tests/test_price_history_producers.py` (신규)

**Interfaces:**
- Consumes: Task 1의 `hist_fingerprint`
- Produces: 후보 stock dict에 `price_history: list[{'date','close'}]`(과거→최신, 25행)와 `hist_fp: str`. 기존 `range_history`·`sparkline_price`는 **이 태스크에서 유지**한다(Task 9에서 제거).

- [ ] **Step 1: Write the failing tests**

두 생산자를 `naver_api.investor_trend`를 가짜로 바꿔 각각 호출하고 검증한다. 가짜는 25행을 날짜 내림차순으로 돌려준다.

```python
def test_both_producers_request_25_rows():
    """종가 이력이 25행이어야 당일을 빼고도 20일 채널이 선다."""
    # investor_trend 호출 인자를 기록해 days=25를 단언

def test_price_history_is_dated_and_oldest_first():
    # price_history[0]['date'] < price_history[-1]['date'], 길이 25

def test_supply_series_still_use_first_20_rows():
    """수급 창이 25일로 넓어지면 심2·심9-1 신호 분포가 조용히 바뀐다."""
    # amount_history 길이 == 20, 외국인/기관 20일 누적이 rows[:20] 합과 같다

def test_hist_fp_present_and_matches_history():
    # stock['hist_fp'] == hist_fingerprint(stock['price_history'])

def test_producers_agree():
    """같은 응답을 두 생산자에 먹이면 price_history가 같다."""
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_price_history_producers.py -q`
Expected: FAIL — `price_history` 키 없음 / `days=20`

- [ ] **Step 3: Implement**

두 생산자 모두 `naver_api.investor_trend(code, days=25, …)`로 바꾸고, `price_history = [{'date': r['date'], 'close': r['close']} for r in reversed(rows)]`를 채운다(`close`가 `None`인 행은 넣지 않는다). **수급 계열은 `rows[:20]`에서 만든다** — `amount_history`·외국인/기관 누적·`foreign_change`·`prev_close`가 해당한다. `hist_fp`도 같이 채운다.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_price_history_producers.py tests/test_sim5_parity.py -q`
Expected: 모두 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_price_history_producers.py src/pipeline/workers/trade_engine.py src/pipeline/workers/data_fetcher.py
git commit -m "feat: 생산자가 날짜를 보존하고 종가 25행·수급 20행으로 분리"
```

---

### Task 3: 보유 종목 이력 공급 — `supply_holding_history`

**Files:**
- Create: `src/trade/holding_history.py`
- Modify: `src/pipeline/workers/trade_engine.py:625` (`sim.run` 직전)
- Modify: `src/pipeline/workers/program_trader.py:1315` (`sim.run` 직전)
- Modify: `src/strategy/simulators/base_simulator.py` (`_view`에 `price_history` 추가, 인스턴스 속성 기본 `{}`)
- Test: `tests/test_holding_history.py` (신규)

**Interfaces:**
- Consumes: `KISDataProvider.get_daily_history(code, days) -> list[dict]`(각 원소에 `date`·`close`), Task 1의 판독기
- Produces:
  - `supply_holding_history(codes, cand_by_code, provider, *, log=print) -> dict[str, list[dict]]`
    — `codes`는 종목코드를 순회할 수 있는 것(포트폴리오 dict도 그대로 받는다)
  - `HISTORY_DAYS = 25`
  - `BaseSimulator.price_history: dict` 속성과 `_view()['price_history']`

- [ ] **Step 1: Write the failing tests**

```python
def test_skips_codes_already_in_candidates():
    """후보에 이력이 있으면 콜 0이다."""

def test_fetches_only_the_rest():
    # provider 호출 코드 목록이 보유 − 후보 집합과 같다

def test_failed_lookup_is_absent_not_empty():
    """빈 배열로 채우면 '측정 불가'가 '이력 없음'으로 위조된다."""
    # provider가 []를 준 코드는 결과 dict에 키가 **없다**

def test_delisted_code_does_not_raise():
    # provider가 예외를 던져도 그 코드만 빠지고 나머지는 돌아온다

def test_etf_code_absence_is_logged():
    # 공급 실패 수가 로그 한 줄에 남는다

def test_view_carries_price_history():
    # BaseSimulator 하위 인스턴스에 price_history를 넣으면 _view()에 실려 나온다

def test_view_defaults_to_empty_dict():
    """전환 안 한 심 14개가 영향받지 않는다 — 시그니처를 안 바꾼 이유다."""
    # price_history를 세팅하지 않은 인스턴스의 _view()['price_history'] == {}

def test_both_paths_call_the_same_supplier():
    """스펙 §9#14. 사본이 둘이면 갈린다(2026-08-05 심9-1 유형)."""
    # trade_engine.py와 program_trader.py 소스가 모두
    # 'supply_holding_history'를 호출하고, 각자 구현한 루프가 없다
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_holding_history.py -q`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: Implement**

`supply_holding_history`는 후보에 이력이 있는 코드를 건너뛰고 나머지를 `provider.get_daily_history(code, days=HISTORY_DAYS)`로 받아 `{'date','close'}`만 남긴다. 종목별 예외는 삼키고 그 코드만 뺀다. 마지막에 `공급 N종목 · 실패 M · X.X초` 한 줄을 `log`로 남긴다.

배선: 양 경로에서 `sim.price_history = supply_holding_history(sim.state.get('portfolio', {}), <그 심의 cand_by_code>, provider)`를 `sim.run` 직전에 둔다. 두 곳이 **같은 함수**를 부른다.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_holding_history.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/trade/holding_history.py tests/test_holding_history.py src/pipeline/workers/trade_engine.py src/pipeline/workers/program_trader.py src/strategy/simulators/base_simulator.py
git commit -m "feat: 보유 종목 이력을 KIS 일봉으로 반드시 공급한다"
```

---

### Task 4: 심1 청산 — `avg * 0.015` 상수 제거

**Files:**
- Modify: `src/strategy/simulators/sim1_psych.py:212-227`
- Test: `tests/test_sim1_psych.py` (추가)

**Interfaces:**
- Consumes: Task 1의 `prior_closes_for`, Task 3의 `view['price_history']`
- Produces: 없음

- [ ] **Step 1: Write the failing tests**

```python
def test_no_atr_exit_without_history():
    """이력이 없으면 ATR 익절·손절을 내지 않는다 — 상수로 메우지 않는다."""
    # 보유 1종목, 후보·공급 모두 이력 없음, 현재가는 진입가 −5%
    # → ATR 손절 주문이 없다

def test_hard_and_trailing_exits_still_fire_without_history():
    """적응형을 못 하는 것과 손실을 방치하는 것은 다른 문제다."""
    # peak 대비 트레일링 조건을 만족시키면 SELL이 난다

def test_atr_exit_uses_supplied_history():
    # view['price_history']만으로 ATR 청산이 난다(후보에는 없다)

def test_atr_differs_by_stock():
    # 변동성이 다른 두 종목에서 손절선이 다르다(상수였으면 같다)

def test_no_constant_fallback_literal_in_source():
    assert '0.015' not in open('src/strategy/simulators/sim1_psych.py', encoding='utf-8').read()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_sim1_psych.py -q`
Expected: FAIL — 상수 폴백이 ATR 손절을 내고, 리터럴 가드도 실패

- [ ] **Step 3: Implement**

`sparkline`·`avg * 0.015` 두 줄을 `hist = prior_closes_for(code, cand_by_code, view, today, 5)`로 바꾼다. `hist is None`이면 ATR 두 갈래를 건너뛰고 funnel에 결손 사유를 남긴다(심5의 `exit_no_hist`와 같은 모양). `atr = BaseSimulator.calculate_atr(hist)`.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_sim1_psych.py tests/test_sim1_program_parity.py -q`
Expected: 모두 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_sim1_psych.py src/strategy/simulators/sim1_psych.py
git commit -m "fix: 심1 ATR 청산의 상수 폴백 제거 — 측정 불가는 측정 불가로"
```

---

### Task 5: 심4(모멘텀) 청산 — `atr_pct = 3.0` 상수 제거

**Files:**
- Modify: `src/strategy/simulators/sim4_bull_momentum.py:61-78`
- Test: `tests/test_sim4_atr_fallback.py` (신규)

**Interfaces:**
- Consumes: Task 1·3과 동일
- Produces: 없음

- [ ] **Step 1: Write the failing tests**

Task 4와 같은 다섯 가지를 심4에 대해. 리터럴 가드는 `atr_pct = 3.0`.

```python
def test_no_atr_stop_without_history()
def test_hard_stop_still_fires_without_history()
def test_atr_stop_uses_supplied_history()
def test_stop_differs_by_stock()
def test_no_constant_fallback_literal_in_source()   # 'atr_pct = 3.0' 부재
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_sim4_atr_fallback.py -q`
Expected: FAIL — `−9%` 고정 손절이 난다

- [ ] **Step 3: Implement**

`sparkline`·`atr_pct = 3.0` 갈래를 `prior_closes_for(…, 5)`로 바꾸고 `None`이면 ATR 손절을 건너뛰고 funnel에 남긴다. 클래스 내부라 `self._view(current_prices)`로 `price_history`를 얻는다.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_sim4_atr_fallback.py tests/test_sim4_adx_ceiling.py -q`
Expected: 모두 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_sim4_atr_fallback.py src/strategy/simulators/sim4_bull_momentum.py
git commit -m "fix: 심4 ATR 손절의 상수 폴백 제거"
```

---

### Task 6: 심3 — ADX는 같은 값, 반등 게이트는 부활

**Files:**
- Modify: `src/strategy/simulators/sim3_risk.py:169-177`
- Test: `tests/test_sim3_rebound_gate.py` (신규)

**Interfaces:**
- Consumes: Task 1·3
- Produces: 없음

- [ ] **Step 1: Write the failing tests**

```python
def test_adx_input_is_still_five_values():
    """진입은 당일을 살린다 — ADX 동작을 바꾸지 않는 것이 목표다."""
    # prior_closes(…, 4) + [현재가] == 지금의 sparkline 5값과 같은 리스트

def test_rebound_gate_now_rejects():
    """배포 이래 한 번도 작동하지 않은 게이트다."""
    # 오늘 종가 <= 5거래일 전 종가인 후보 → funnel에 'no_rebound'

def test_rebound_gate_passes_when_rebounding():
    # 오늘 종가 > 5거래일 전 종가 → 통과(다른 게이트로 넘어간다)

def test_new_listing_without_history_is_recorded_not_silent():
    """이력 20일 미만 종목이 조용히 사라지지 않는다."""
    # prior_closes None → funnel에 결손 사유가 남는다
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_sim3_rebound_gate.py -q`
Expected: FAIL — `no_rebound`가 한 번도 나오지 않는다

- [ ] **Step 3: Implement**

ADX는 `prior_closes_for(code, candidate_map, view, today, 4)`에 현재가를 붙여 **5값**으로 유지한다. 반등 게이트는 `prior_closes_for(…, 5)`에 현재가를 붙여 **6값**으로 만들어 `vals[-1] <= vals[-6]`을 판정한다. 어느 쪽이든 `None`이면 funnel에 결손 사유를 남기고 그 후보를 건너뛴다.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_sim3_rebound_gate.py tests/test_sim3_timestop_and_funnel.py -q`
Expected: 모두 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_sim3_rebound_gate.py src/strategy/simulators/sim3_risk.py
git commit -m "fix: 심3 반등 게이트 부활 — 이력 5개에 6개를 요구해 죽어 있었다"
```

---

### Task 7: 심4-1 진입 ADX — 값 불변 전환

**Files:**
- Modify: `src/strategy/simulators/sim4_bull_daytrading.py:142-150`
- Test: `tests/test_sim4_1_entry_funnel.py` (추가)

**Interfaces:**
- Consumes: Task 1·3
- Produces: 없음

- [ ] **Step 1: Write the failing test**

```python
def test_adx_input_unchanged_after_migration():
    """실전 선택 중인 심이다 — 진입 동작이 바뀌면 안 된다."""
    # prior_closes(…, 4) + [현재가]가 지금의 sparkline 5값과 같고, 같은 후보가 같은 결정을 받는다
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_sim4_1_entry_funnel.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**

`sparkline` 읽기를 `prior_closes_for(…, 4) + [price]`로 바꾼다. `None`이면 기존 `no_sparkline` 사유를 유지한다.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_sim4_1_entry_funnel.py tests/test_sim4_1_parity.py -q`
Expected: 모두 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_sim4_1_entry_funnel.py src/strategy/simulators/sim4_bull_daytrading.py
git commit -m "refactor: 심4-1 ADX 입력을 이력 계약으로 전환(값 불변)"
```

---

### Task 8: 심5 — 채널·RSI2에서 당일 제거

**Files:**
- Modify: `src/strategy/simulators/sim5_sideways_swing.py:73-101,130-150,195-215`
- Test: `tests/test_sim5_channel_prior_day.py` (신규)

**Interfaces:**
- Consumes: Task 1·3
- Produces: 없음

⚠ **스펙 §4.2의 장중 관측(11-30) 전에는 이 태스크를 병합하지 않는다.** 코드는 날짜 기준이라 관측과 무관하게 옳지만, 서명 항목 ③(심5 진입 빈도)의 유효성이 관측에 걸려 있다.

- [ ] **Step 1: Write the failing tests**

```python
def test_channel_excludes_today_even_when_today_is_the_low():
    """하락일에 '저점 +3% 이내'가 자동 통과하던 자리다."""
    # 이력 20일 + 당일(최저가) → low가 당일 종가가 아니다

def test_channel_window_stays_20_with_25_rows():
    """25행을 받아도 채널은 20일이다 — 전략 상수를 바꾸지 않는다."""
    # 25행 중 가장 오래된 5행의 극단값이 low/high에 영향을 주지 않는다

def test_rsi2_counts_today_once():
    # 당일이 이력에 든 입력과 안 든 입력의 RSI2가 다르고, 후자가 쓰인다

def test_entry_possible_with_25_rows_and_blocked_with_20():
    """§4.1 회귀 가드: 20행이면 당일 제외 후 19행이라 채널이 안 선다."""
    # 20행 픽스처 → funnel 'no_channel'; 25행 픽스처 → 진입 발생

def test_exit_rsi2_skipped_without_history_but_hard_stop_fires():
    # 기존 exit_no_hist 경로가 유지되고 −5% 하드 손절은 난다
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_sim5_channel_prior_day.py -q`
Expected: FAIL — 채널 저점이 당일 종가다

- [ ] **Step 3: Implement**

`_hist`·`_channel` 호출부를 `prior_closes_for(code, cand_by_code, view, today, MIN_HISTORY)`로 바꾼다. 진입·청산 RSI2는 `rsi2(hist + [cur])`를 **유지**한다 — 중복 계산은 `hist`에서 당일이 빠지면서 사라진다. `_hist`는 호출자가 없어지면 제거한다.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_sim5_channel_prior_day.py tests/test_sim5_parity.py tests/test_sim5_regime_gate.py -q`
Expected: 모두 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_sim5_channel_prior_day.py src/strategy/simulators/sim5_sideways_swing.py
git commit -m "fix: 심5 채널·RSI2에서 당일 제거 — 설계서 7절과 일치시킨다"
```

---

### Task 9: 구 필드 제거 + 범위 가드

**Files:**
- Modify: `src/pipeline/workers/trade_engine.py`·`src/pipeline/workers/data_fetcher.py` (`range_history`·`sparkline_price` 생산 제거)
- Modify: `src/data/schemas.py:62-63`
- Modify: `src/strategy/strategy_manifest.yaml:155` (심5 `needs_buzz` 주석 — 근거가 낡았다)
- Test: `tests/test_price_history_contract.py` (가드 추가)

**Interfaces:**
- Consumes: Task 2·4~8 완료
- Produces: 없음

- [ ] **Step 1: Write the failing guard**

```python
def test_old_fields_gone_from_decision_paths():
    """매매 판단 경로에만 적용한다 — 심9-1(EOD)과 표시용 소비자는 범위 밖이다.

    **식별자가 아니라 필드 접근을 센다.** 2026-11-28 실측: 맨 식별자로 세면
    `base_simulator.py`(세 통계 함수의 **파라미터 이름**)와
    `sim10_orchestrator.py:56`(**docstring 언급**)이 거짓으로 걸린다. 둘 다
    결함이 아니다.
    """
    EXEMPT = {'sim9_1_donchian.py',      # EOD — 생산자가 이미 직전 20일
              'sim0_libero.py',           # breadth 표시용 ⚠ 아래 참조
              'us_sim2_donchian.py',      # 미국 심
              'notifier.py'}              # 런마다 append하는 표시용 5일 시계열
    # src/strategy/ · src/pipeline/ 아래 .py 중 EXEMPT 제외 파일에
    # 아래 **필드 접근 형태**가 없다:
    #   .get('range_history'  ·  ['range_history']  ·  'range_history']
    #   .get('sparkline_price' · ['sparkline_price'] · 'sparkline_price']
```

- [ ] **Step 1b: 감사기가 헬퍼 경로를 보게 한다 (실패하는 테스트 먼저)**

```python
def test_audit_sees_history_read_through_helper():
    """`prior_closes_for(...)`로 읽는 `price_history`가 감사에 잡힌다.

    `scripts/audit_sim_fields.py:27`의 `FIELD_RE`는 `stock.get('x')` 같은 **직접
    접근만** 잡는다. 심들이 이력을 헬퍼로 읽게 된 뒤로는 `price_history`가 감사의
    사각에 들어갔다 — **이 작업의 가장 중요한 필드가 "유니버스가 실제로 채우는가"
    검사에서 빠진 것이다.** 그 감사기는 심5가 `amount` 미배선으로 배포 이래 거래
    0건이던 사고 뒤에 만들어졌다. 같은 고장이 다시 들어올 문을 열어 두면 안 된다.
    """
    # prior_closes_for(code, cand_by_code, view, today, n)를 부르는 심 소스에서
    # 감사기가 'price_history'를 읽은 필드로 보고한다
```

⚠ **이 EXEMPT 목록은 최종 리뷰에서 틀린 것으로 판정됐다.** `sim0_libero.py`를 면제한
것은 "표시용이니 손대지 말라"는 뜻이었는데, **그 소비자의 생산자를 이 태스크가 지웠다** —
그래서 `sparkline_price`가 항상 `[]`가 되고 `momentum`·`trend`가 **조용히 0.0**이 됐다
(`regime_observations.py:44`가 "0은 '최악의 장'"이라고 금지하는 값이다). 면제의 뜻은
"구 필드를 의도적으로 **남긴다**"이지 "소비자의 생산자가 사라져도 된다"가 아니다.
수정 웨이브에서 `sim0_libero`를 `price_history`로 전환하고 **EXEMPT에서 뺐다.**
같은 고장을 엑셀 열에서는 이 태스크가 잡아 고쳤다 — 기준이 일관되지 않았던 것이 원인이다.

추가로 이 태스크에서 둘을 같이 정리한다 — 필드가 사라진 뒤에도 남으면 **이름과
값이 어긋난 채 영구히 사는** 자리다:

- `base_simulator.py:528,568,606` — `calculate_atr`·`calculate_adx`·
  `calc_period_change`의 파라미터 이름 `sparkline_price`를 `closes`로 바꾼다.
  2026-11-28 실측: 전 호출부가 **위치 인자**라(키워드 사용 0건) 호출부 변경이 없다.
- `sim10_orchestrator.py:56` — docstring의 `range_history` 언급을 새 필드명으로 고친다.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_price_history_contract.py::test_old_fields_gone_from_decision_paths -q`
Expected: FAIL — 생산자·스키마에 남아 있다

- [ ] **Step 3: Implement**

생산자에서 두 필드를 걷어낸다. 단 **심9-1이 소비하는 `range_history`는 `run_eod_sims.py` 생산자에 그대로 둔다**(EOD 비목표). 심9-1 소비 지점에 "EOD 전용 · 생산자가 이미 직전 20일" 주석을 박는다. `schemas.py`는 `price_history`로 교체한다. 표시용 소비자(`notifier`·`storage_manager`·`analyzer_5days`·`src/app/research/*`)는 손대지 않는다 — 각자 자기 경로로 채운다.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest tests -q` 그리고 `npx tsc --noEmit`
Expected: 전부 PASS (전환 전 기준선 2,673+ passed)

- [ ] **Step 5: Commit**

```bash
git add -u && git commit -m "refactor: 매매 판단 경로에서 구 이력 필드 제거(EOD·표시용 제외)"
```

---

### Task 10: 파리티 해시 · 연속 결손 알림

**Files:**
- Modify: `src/data/decision_log.py:47-53` (`INPUT_FIELDS`에 `hist_fp` 추가)
- Modify: `src/trade/holding_history.py` (연속 결손 알림)
- Test: `tests/test_decision_log.py` (추가) · `tests/test_holding_history.py` (추가)

**Interfaces:**
- Consumes: Task 2의 `hist_fp`, Task 3의 공급 함수
- Produces: 없음

- [ ] **Step 1: Write the failing tests**

```python
def test_input_hash_changes_when_history_window_changes():
    """이력이 청산 임계값을 정하는데 해시가 그걸 안 보면,
    폰/그림자 비교가 '같은 입력, 다른 결정'을 양쪽으로 거짓 보고한다."""
    # hist_fp만 다른 두 stock dict의 input_hash가 다르다

def test_input_hash_unchanged_when_history_absent():
    # hist_fp 키가 없으면 기존 해시와 같다(기존 행과의 비교가 깨지지 않는다)

def test_repeated_supply_failure_alerts_once():
    # 같은 종목이 연속 실패하면 send_alert_once가 한 번만 호출된다(60분 쿨다운)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_decision_log.py tests/test_holding_history.py -q`
Expected: FAIL

- [ ] **Step 3: Implement**

`INPUT_FIELDS`에 `'hist_fp'`를 더한다(기존 항목은 건드리지 않는다 — 없는 필드는 해시에 기여하지 않으므로 옛 행과의 비교가 유지된다). 공급 실패는 `src/alerts.py`의 `send_alert_once(key=f'hist_missing_{code}', …, cooldown_min=60)`으로 알린다. **새 상태 파일을 만들지 않는다**(`alert_dedup.json` 배선 선례).

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_decision_log.py tests/test_holding_history.py -q`
Expected: 모두 PASS

- [ ] **Step 5: Commit**

```bash
git add -u && git commit -m "feat: 이력 지문을 파리티 해시에 넣고 공급 실패를 알린다"
```

---

## 돌연변이 리허설 (Task 4·5·6·8 각각의 Step 4 뒤)

고친 줄을 옛 코드로 되돌려 **새 테스트가 실패하는지** 확인하고 복구한다. 통과만 보면
테스트가 그 갈래를 지나는지 알 수 없다 — 심9 `_fn` 버그가 그렇게 살았다.

## 배포 후 검증 지점 (PR 본문에 들어갈 표)

| 언제 | 어디서 | 무엇이 보이면 |
|---|---|---|
| 첫 장중 런 | Actions 로그 | `보유 이력 공급 N종목 M초`. M > 3초면 스펙 A안(공짜 레그)을 올린다 |
| 첫 장중 런 | 심1·심4 청산 사유 | `ATR 기반`이 찍히고 그 값이 **종목마다 다르다**(전부 같으면 상수가 살아 있다) |
| 11-30 장중 | 읽기 전용 관측 | `investor_trend` 첫 행 날짜 vs 그날 KST 날짜 — 스펙 §4.2 |
| 첫 장중 런 | 심3 funnel | `no_rebound`가 **처음으로** 나타난다. 0건이면 게이트가 아직 죽어 있다 |
| 심5 배포 후 1주 | 심5 진입 건수 | **0건이 아니면서** 전주보다 줄어든다. 0건은 §4.1 고장의 신호이므로 실패 판정 |
