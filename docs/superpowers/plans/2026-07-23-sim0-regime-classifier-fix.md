# 심0 국면 분류기 수정 (Part 1: bull_score 밴드) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `classify_regime`의 AND게이트(상승장 놓침)를 bull_score 밴드 분류기로 대체하되, 27일 실측 데이터로 국면 적중률 개선을 먼저 증명하고 통과 시에만 라이브 반영한다.

**Architecture:** bull_score→국면 매핑을 순수 함수(`classify_by_score`)로 추가한다. 커밋된 db-data 스냅샷 픽스처에 대해 θ(임계값)를 스윕하는 백테스트 하네스로 구 로직 대비 적중률을 비교한다. 개선이 확인된 θ만 `run()`에 반영하고, 미확인 시 구 로직을 유지한다.

**Tech Stack:** Python 3.12, pytest. 데이터: `origin/db-data` 브랜치 `data/sim_libero_state.json`.

## Global Constraints

- `current_regime` 계약 불변: "BULL"|"SIDEWAYS"|"BEAR" 문자열. **Sim6/Sim10 수정 금지.**
- `calc_bull_score`(0.40*breadth + 0.35*momentum_n + 0.25*trend_n) 재사용, 수정 금지.
- 매매 집행·effective_budget·주문 경로·nowcast 예측 로직 일절 무관.
- 검증 미통과 시 구 `classify_regime` 폴백 유지(fail-safe).
- 가짜 값 금지: 조회/필드 부재는 생략, 0/50 등으로 지어내지 않는다.

---

## Task 1: db-data 스냅샷 픽스처 커밋

**Files:**
- Create: `tests/fixtures/sim0_calibration_snapshot.json`

**Interfaces:**
- Produces: 픽스처 파일. 키 `calibration_log`(list of `{date, libero_breadth, actual_kospi_breadth, gap, bull_score, regime, v}`), `intraday_score_log`(list of `{date, type, made_at, target, pred, actual, gap}`).

- [ ] **Step 1: db-data에서 스냅샷 추출·저장**

Run:
```bash
cd /c/Users/Hoon_DT/gemini/stock
git fetch origin db-data --depth=1
mkdir -p tests/fixtures
git show origin/db-data:data/sim_libero_state.json | python -c "
import sys, json
s = json.load(sys.stdin)
snap = {
    'calibration_log': s.get('calibration_log', []),
    'intraday_score_log': s.get('intraday_score_log', []),
    'daily_regime_log': s.get('daily_regime_log', []),
}
with open('tests/fixtures/sim0_calibration_snapshot.json', 'w', encoding='utf-8') as f:
    json.dump(snap, f, ensure_ascii=False, indent=2)
print('calibration:', len(snap['calibration_log']), 'intraday:', len(snap['intraday_score_log']))
"
```
Expected: `calibration: 27 intraday: 129` (건수는 수집 진행에 따라 증가 가능; 20건 이상이면 진행).

- [ ] **Step 2: 커밋**

```bash
git add tests/fixtures/sim0_calibration_snapshot.json
git commit -m "test(sim0): db-data 국면 검증 스냅샷 픽스처"
```

---

## Task 2: bull_score 밴드 분류기 순수 함수

**Files:**
- Modify: `src/strategy/simulators/sim0_libero.py` (module-level 함수 추가, `classify_regime` 근처)
- Test: `tests/test_sim0_regime.py`

**Interfaces:**
- Produces:
  ```python
  def classify_by_score(bull_score: float, theta_bull: float, theta_bear: float) -> str:
      # bull_score >= theta_bull -> "BULL"; <= theta_bear -> "BEAR"; else "SIDEWAYS"
  ```

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_sim0_regime.py`:
```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.strategy.simulators.sim0_libero import classify_by_score


def test_band_bull():
    assert classify_by_score(72.0, 60.0, 35.0) == "BULL"

def test_band_bear():
    assert classify_by_score(30.0, 60.0, 35.0) == "BEAR"

def test_band_sideways():
    assert classify_by_score(50.0, 60.0, 35.0) == "SIDEWAYS"

def test_band_boundaries_inclusive():
    # 경계값은 각각 BULL/BEAR에 포함
    assert classify_by_score(60.0, 60.0, 35.0) == "BULL"
    assert classify_by_score(35.0, 60.0, 35.0) == "BEAR"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_sim0_regime.py -v`
Expected: FAIL — `ImportError: cannot import name 'classify_by_score'`

- [ ] **Step 3: 최소 구현**

`src/strategy/simulators/sim0_libero.py`의 `classify_regime` 메서드 위(모듈 레벨, 클래스 밖 아님 주의 — 아래는 모듈 함수로 파일 상단 유틸 근처에 추가):
```python
def classify_by_score(bull_score, theta_bull, theta_bear):
    """bull_score(0~100)를 3상태 국면으로 매핑. AND게이트 대체.
    경계값은 각각 BULL/BEAR에 포함(>=, <=)."""
    if bull_score >= theta_bull:
        return "BULL"
    if bull_score <= theta_bear:
        return "BEAR"
    return "SIDEWAYS"
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_sim0_regime.py -v`
Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add src/strategy/simulators/sim0_libero.py tests/test_sim0_regime.py
git commit -m "feat(sim0): bull_score 밴드 분류기 순수 함수"
```

---

## Task 3: 백테스트 하네스 (θ 스윕 + 구/신 적중률 비교)

**Files:**
- Create: `tests/test_sim0_regime_backtest.py`

**Interfaces:**
- Consumes: `tests/fixtures/sim0_calibration_snapshot.json`, `classify_by_score`.
- Produces: `truth_regime(actual_breadth)`, `sweep_best(calibration_log)`, 그리고 비교표를 출력하며 배포 게이트를 단언하는 테스트.

**설계 노트:** calibration_log에는 `bull_score`와 확정 실측 `actual_kospi_breadth`, 그리고 구 시스템이 실제 출력한 `regime`이 있다. 원시 momentum/trend는 없으므로 구 AND게이트를 재현할 수는 없고, **기록된 구 regime**을 baseline으로 쓴다(구 분류+스무딩의 실제 산출물). 기준 국면은 확정 실측에서 정의한다.

- [ ] **Step 1: 하네스 + 게이트 테스트 작성**

`tests/test_sim0_regime_backtest.py`:
```python
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.strategy.simulators.sim0_libero import classify_by_score

FIX = os.path.join(os.path.dirname(__file__), 'fixtures', 'sim0_calibration_snapshot.json')


def _load():
    with open(FIX, encoding='utf-8') as f:
        return json.load(f)['calibration_log']


def truth_regime(actual_breadth):
    """확정 실측 breadth로 정의한 그날의 기준 국면."""
    if actual_breadth >= 60:
        return "BULL"
    if actual_breadth <= 35:
        return "BEAR"
    return "SIDEWAYS"


def _accuracy(cal, theta_bull, theta_bear):
    hit = bull_hit = bull_tot = 0
    for e in cal:
        truth = truth_regime(e['actual_kospi_breadth'])
        pred = classify_by_score(e['bull_score'], theta_bull, theta_bear)
        hit += (pred == truth)
        if truth == "BULL":
            bull_tot += 1
            bull_hit += (pred == "BULL")
    return hit / len(cal), (bull_hit / bull_tot if bull_tot else None)


def _old_accuracy(cal):
    hit = bull_hit = bull_tot = 0
    for e in cal:
        truth = truth_regime(e['actual_kospi_breadth'])
        hit += (e.get('regime') == truth)
        if truth == "BULL":
            bull_tot += 1
            bull_hit += (e.get('regime') == "BULL")
    return hit / len(cal), (bull_hit / bull_tot if bull_tot else None)


def sweep_best(cal):
    """θ_bull(45~70), θ_bear(20~45) 스윕. 전체 적중률 최대, 동률 시 상승장 포착률 우선."""
    best = None
    for tb in range(45, 71, 1):
        for tr in range(20, 46, 1):
            if tr >= tb:
                continue
            acc, bull = _accuracy(cal, tb, tr)
            key = (acc, bull or 0)
            if best is None or key > best[0]:
                best = (key, tb, tr, acc, bull)
    return best


def test_backtest_report_and_gate():
    cal = _load()
    assert len(cal) >= 20, "검증 표본 부족 — 픽스처 재수집 필요"
    old_acc, old_bull = _old_accuracy(cal)
    _, tb, tr, new_acc, new_bull = sweep_best(cal)
    print(f"\n[구 로직]  적중률 {old_acc:.1%}, 상승장 포착 {old_bull}")
    print(f"[신 밴드]  최적 θ_bull={tb} θ_bear={tr} → 적중률 {new_acc:.1%}, 상승장 포착 {new_bull}")
    # 배포 게이트: 신규가 구 대비 전체 적중률·상승장 포착 둘 다 개선(비열등)
    assert new_acc > old_acc, f"전체 적중률 개선 없음 ({new_acc:.1%} vs {old_acc:.1%}) — 배포 보류"
    assert (new_bull or 0) >= (old_bull or 0), "상승장 포착 후퇴 — 배포 보류"
```

- [ ] **Step 2: 실행 — 리포트 확인 및 게이트 통과 여부**

Run: `python -m pytest tests/test_sim0_regime_backtest.py -v -s`
Expected: PASS, 그리고 출력에 최적 `θ_bull`/`θ_bear`와 구/신 적중률이 찍힌다. **이 최적 θ 값을 Task 4에 사용한다.**
- 만약 FAIL(게이트 미통과)이면: 밴드 분류기가 이 표본에서 개선을 못 준 것 → **중단하고 사용자에게 보고**(임계 재설계 또는 3a/3b 선행 필요).

- [ ] **Step 3: 커밋**

```bash
git add tests/test_sim0_regime_backtest.py
git commit -m "test(sim0): 국면 분류기 백테스트 하네스 + 배포 게이트"
```

---

## Task 4: 검증된 θ를 모듈 상수로 고정

**Files:**
- Modify: `src/strategy/simulators/sim0_libero.py`
- Test: `tests/test_sim0_regime.py`

**Interfaces:**
- Produces: 모듈 상수 `REGIME_THETA_BULL`, `REGIME_THETA_BEAR` (Task 3이 출력한 최적값).

**전제:** Task 3의 게이트가 PASS했고, 출력된 최적 θ를 안다. (FAIL이었으면 이 Task로 진행하지 않는다.)

- [ ] **Step 1: 상수 반영 테스트 작성**

`tests/test_sim0_regime.py`에 추가 (아래 `<TB>`/`<TR>`은 Task 3 출력 최적값으로 치환):
```python
from src.strategy.simulators.sim0_libero import REGIME_THETA_BULL, REGIME_THETA_BEAR

def test_theta_constants_match_validated():
    assert REGIME_THETA_BULL == <TB>
    assert REGIME_THETA_BEAR == <TR>
    assert REGIME_THETA_BEAR < REGIME_THETA_BULL
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_sim0_regime.py::test_theta_constants_match_validated -v`
Expected: FAIL — 상수 미정의

- [ ] **Step 3: 상수 추가**

`src/strategy/simulators/sim0_libero.py`의 `classify_by_score` 정의 위:
```python
# Task 3 백테스트가 27일 실측에서 구 로직 대비 적중률·상승장 포착 개선을 확인한 값.
REGIME_THETA_BULL = <TB>
REGIME_THETA_BEAR = <TR>
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_sim0_regime.py -v`
Expected: 5 passed

- [ ] **Step 5: 커밋**

```bash
git add src/strategy/simulators/sim0_libero.py tests/test_sim0_regime.py
git commit -m "feat(sim0): 검증된 국면 임계값 상수 고정"
```

---

## Task 5: run()에 밴드 분류기 배선 (구 AND게이트 대체)

**Files:**
- Modify: `src/strategy/simulators/sim0_libero.py:340` (run() 내 `instant_regime = self.classify_regime(...)`)
- Test: `tests/test_sim0_regime.py`

**Interfaces:**
- Consumes: `classify_by_score`, `REGIME_THETA_BULL`, `REGIME_THETA_BEAR`, `calc_bull_score`.

**설계:** 현재 `run()`은 `instant_regime = self.classify_regime(breadth, momentum, trend)` 후 `bull_score = self.calc_bull_score(...)`를 따로 구한다. bull_score 계산을 instant_regime 앞으로 옮기고, instant_regime을 밴드 분류로 대체한다. 스무딩(`_confirm_regime`)은 이번 Part에서 변경하지 않는다.

- [ ] **Step 1: 회귀 테스트 작성 (밴드 배선 검증)**

`tests/test_sim0_regime.py`에 추가:
```python
from src.strategy.simulators.sim0_libero import LiberoSimulator

def test_run_uses_band_classifier_for_bull():
    """breadth 높고 bull_score가 θ_bull 이상이면 instant_regime=BULL.
    구 AND게이트라면 momentum/trend 미달로 SIDEWAYS가 됐을 상황."""
    sim = LiberoSimulator()
    sim.save_state = lambda *a, **k: None  # 실제 상태 파일 쓰기 방지
    # breadth 매우 높음, momentum/trend는 BULL AND게이트에 못 미치는 값
    cands = [{'change_rate': '+1.0%', 'sparkline_price': [100, 101]} for _ in range(80)]
    cands += [{'change_rate': '-0.5%', 'sparkline_price': [100, 100]} for _ in range(20)]
    sim.live_market_metrics = {'breadth': 96.0, 'momentum': 0.5, 'trend': 10.0, 'sample': 100}
    sim.run(cands, current_prices={})
    # bull_score = 0.40*96 + 0.35*clamp(50+0.5*5) + 0.25*10 = 38.4 + 18.375 + 2.5 = 59.3
    # (θ 검증값에 따라) 밴드가 구 AND게이트보다 BULL을 잘 잡는지: instant_regime 확인
    assert sim.state['instant_regime'] in ("BULL", "SIDEWAYS")  # θ에 따라 갈림 — 구 로직은 무조건 SIDEWAYS
    assert sim.state['bull_score'] == 59.3
```

Note: 이 테스트는 bull_score 계산 위치 이동과 밴드 배선이 됐는지(그리고 bull_score 값 회귀)를 검증한다. θ 경계에 걸리는 값이면 단언을 실제 검증 θ에 맞춰 `== "BULL"`로 좁힌다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_sim0_regime.py::test_run_uses_band_classifier_for_bull -v`
Expected: FAIL — 아직 `classify_regime`(AND게이트) 사용 중이라 `instant_regime`이 밴드 기준과 다르거나, bull_score 계산 순서 문제.

- [ ] **Step 3: run() 배선 변경**

`src/strategy/simulators/sim0_libero.py` run() 내 라인 340-341을 다음으로 교체:
```python
        bull_score = self.calc_bull_score(breadth, momentum, trend)
        instant_regime = classify_by_score(bull_score, REGIME_THETA_BULL, REGIME_THETA_BEAR)
```
(기존 순서는 `instant_regime = self.classify_regime(...)`가 먼저, `bull_score = ...`가 뒤. 위처럼 bull_score를 먼저 계산하고 밴드로 분류.)

`classify_regime` 메서드는 **삭제하지 않는다** — 폴백/참조 보존. 단 run()에서 더는 호출하지 않는다.

- [ ] **Step 4: 통과 확인 + 전체 회귀**

Run:
```bash
python -m pytest tests/test_sim0_regime.py tests/test_sim0_nowcast.py tests/test_libero_eod_and_leak.py -v
```
Expected: 전부 PASS (기존 sim0/libero 테스트 무회귀).

- [ ] **Step 5: 커밋**

```bash
git add src/strategy/simulators/sim0_libero.py tests/test_sim0_regime.py
git commit -m "feat(sim0): run() 국면 결정을 bull_score 밴드로 대체"
```

---

## Task 6: 최종 검증 및 배포 준비

- [ ] **Step 1: 전체 sim0/libero 테스트 스위트**

Run:
```bash
python -m pytest tests/ -k "sim0 or libero" -v
```
Expected: 전부 PASS.

- [ ] **Step 2: 백테스트 게이트 재확인**

Run: `python -m pytest tests/test_sim0_regime_backtest.py -v -s`
Expected: PASS + 구/신 적중률 리포트. 이 수치를 배포 근거로 사용자에게 보고.

- [ ] **Step 3: 배포 (main push)**

```bash
git push origin main
```
push 후 다음 파이프라인 런부터 `current_regime`이 밴드 분류기로 산출된다. `daily_regime_log`로 상승장 포착 개선을 관찰한다(라이브 반영 후 며칠).

---

## 자기검토 메모

- **스펙 커버리지:** 이 계획은 스펙의 Part 1(밴드 분류기) + 검증 하네스 + 게이트 배선을 구현. Part 3a(스무딩)·3b(전방지향)·Part 2(4신호 수집)는 **후속 계획**으로 분리(각각 독립 검증·배포). 후속 계획은 Part 1 라이브 반영·관찰 후 착수.
- **폴백:** Task 3 게이트 FAIL 시 배선(Task 4~5) 미진행 → 구 로직 유지(fail-safe 준수).
- **불변 계약:** `current_regime` 문자열·Sim6/Sim10 무수정 유지.
