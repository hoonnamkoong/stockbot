# Sim1 프로그램 매매 파리티 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 프로그램 매매 경로에서도 Sim1이 페이퍼와 **완전히 동일한 이력 입력**(`d_sov`·`d_hype`·`accel`)으로 돌게 만들고, 두 경로의 진단 로그를 분리한다.

**Architecture:** 페이퍼 Sim1이 이번 런에 **실제로 소비한** 이력 쌍 `(prev_day, last_run)`을 state에 남긴다(`psych_last_run` 슬롯 신설). `program_trader`는 실계좌 스냅샷 state를 만들 때 그 쌍을 `psych_prev_day`/`psych_snapshot` 자리에 주입한다. `resolve_history`가 이 입력에 멱등이라 재승격 없이 같은 쌍이 그대로 흘러간다. 진단 로그는 `exec_path` 플래그로 별도 CSV로 갈라진다.

**Tech Stack:** Python 3.12, pytest, 표준 라이브러리만. 네트워크 호출 없음.

**설계 문서:** [docs/superpowers/specs/2026-07-29-sim1-program-parity-design.md](../specs/2026-07-29-sim1-program-parity-design.md)

## Global Constraints

- **매매 동작은 바뀌지 않는다.** `ignition4`는 여전히 진입에 쓰이지 않는다. 이 작업은 기록만 정확하게 만든다. 진입식 교체는 Phase 2다.
- **현행보다 나빠지지 않는다.** 페이퍼 state가 없거나 dict가 아니면 프로그램은 지금과 똑같이 `hist_missing=1`로 동작한다(예외를 던지지 않는다).
- **진단 CSV 컬럼은 변경 금지.** `sim_diag.COLUMNS`를 건드리면 헤더 회전이 일어나 07-29 수확분(569행)이 `_v1` 파일로 갈라진다.
- Sim1의 매니페스트 id는 `sim_psych`, 진단 키는 `sim1`. **둘은 다르다** — 진단 키를 `sim_id`에서 유도하지 말 것.
- 테스트에서 `PsychDivergenceSimulator` 인스턴스를 만들면 **생성 직후 즉시** `state_file`·`log_file`·`csv_file`을 임시 디렉터리로 교체한다. 실제 `data/sim_psych_state.json`을 절대 건드리지 않는다.
- 실행: `python -m pytest tests/... -v` (프로젝트 루트에서, `PYTHONPATH` 불필요 — 테스트 파일이 `sys.path`를 직접 세운다).

---

## File Structure

| 파일 | 역할 | 변경 |
|---|---|---|
| `src/strategy/simulators/sim1_psych.py` | Sim1 전략. `run()`이 이력 승격·진단 기록을 담당 | 수정 (`run()` 2곳) |
| `src/pipeline/workers/program_trader.py` | 프로그램 매매. 실계좌 스냅샷 state 구성 | 수정 (헬퍼 1개 신설 + 스냅샷 dict) |
| `tests/test_sim1_program_parity.py` | 이 작업의 전용 테스트 | **신설** |

---

## Task 1: sim1이 소비한 이력 쌍을 state에 남긴다

**Files:**
- Modify: `src/strategy/simulators/sim1_psych.py:387-389`
- Test: `tests/test_sim1_program_parity.py` (신설)

**Interfaces:**
- Consumes: 기존 `resolve_history(prev_day, snapshot, today) -> (prev_day, last_run)` (같은 파일 53행)
- Produces: `PsychDivergenceSimulator.run()` 실행 후 `sim.state['psych_last_run']`에 이번 런이 소비한 `last_run`(dict 또는 `None`)이 들어 있다. Task 3이 이 키를 읽는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_sim1_program_parity.py`를 새로 만들고 아래 내용을 넣는다.

```python
"""Sim1 프로그램 매매 파리티.

프로그램 경로는 sim.state가 실계좌 스냅샷으로 갈아끼워져 이력 슬롯이 없다.
그래서 d_sov·d_hype·accel이 항상 0이었다. Phase 2에서 accel>0 게이트가
들어가면 프로그램 Sim1은 영구 무매매가 된다 — 조용히 안 사는 것은 잘못
사는 것만큼 나쁘다.

설계: docs/superpowers/specs/2026-07-29-sim1-program-parity-design.md
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators.sim1_psych import (
    PsychDivergenceSimulator, resolve_history, decide_psych, MIN_SAMPLE,
)


def _isolated_sim(tmpdir):
    """실제 data/sim_psych_state.json을 건드리지 않는 격리 인스턴스."""
    sim = PsychDivergenceSimulator(initial_cash=3_000_000)
    sim.state_file = os.path.join(tmpdir, 'sim_psych_state.json')
    sim.log_file = os.path.join(tmpdir, 'sim_psych_log.json')
    sim.csv_file = os.path.join(tmpdir, 'trade_history_sim_psych.csv')
    sim.reset_state()
    return sim


def _snap(date, z_sov=1.0, z_posters=1.0, z_hype=0.5):
    return {'date': date, 'ts': f'{date} 10:00:00',
            'z': {'005930': {'z_sov': z_sov, 'z_posters': z_posters, 'z_hype': z_hype}}}


# ── Task 1: 소비한 쌍을 state에 남긴다 ──────────────────────
def test_run_stores_consumed_last_run():
    """같은 날 두 번째 런이면 소비한 last_run은 직전 런 스냅샷이다."""
    with tempfile.TemporaryDirectory() as d:
        sim = _isolated_sim(d)
        import datetime as _dt
        today = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=9))).strftime('%Y%m%d')
        earlier = _snap(today, z_sov=1.0)
        sim.state['psych_snapshot'] = earlier

        sim.run([], current_prices={})

        assert sim.state['psych_last_run'] == earlier


def test_run_stores_none_on_first_run_of_day():
    """전일 스냅샷만 있으면 승격이 일어나고 소비한 last_run은 None이다."""
    with tempfile.TemporaryDirectory() as d:
        sim = _isolated_sim(d)
        yesterday = _snap('20260101')  # 오늘일 수 없는 날짜
        sim.state['psych_snapshot'] = yesterday

        sim.run([], current_prices={})

        assert sim.state['psych_last_run'] is None
        assert sim.state['psych_prev_day'] == yesterday
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_sim1_program_parity.py -v`
Expected: 두 테스트 모두 FAIL — `KeyError: 'psych_last_run'`

- [ ] **Step 3: 최소 구현**

`src/strategy/simulators/sim1_psych.py`의 `run()`에서 387-389행을 찾는다.

```python
        self.state['psych_prev_day'] = prev_day
        if snapshot.get('z'):
            self.state['psych_snapshot'] = snapshot
```

아래로 바꾼다.

```python
        self.state['psych_prev_day'] = prev_day
        # 이번 런이 실제로 소비한 직전 런. 페이퍼는 안 읽는다 — 프로그램 매매
        # 경로가 '페이퍼와 같은 입력'을 승계하기 위한 슬롯이다. psych_snapshot은
        # 바로 아래에서 이번 런 값으로 덮어써지므로 그걸 넘기면 accel이 0이 된다.
        self.state['psych_last_run'] = last_run
        if snapshot.get('z'):
            self.state['psych_snapshot'] = snapshot
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_sim1_program_parity.py -v`
Expected: 2 passed

- [ ] **Step 5: 회귀 확인**

Run: `python -m pytest tests/test_sim1_psych.py -v`
Expected: 16 passed

Run: `python scratch/test_sim1_history.py`
Expected: 전부 PASS (FAIL 줄이 하나도 없어야 한다)

- [ ] **Step 6: 커밋**

```bash
git add src/strategy/simulators/sim1_psych.py tests/test_sim1_program_parity.py
git commit -F - << 'EOF'
feat(sim1): 소비한 이력 쌍을 state에 남긴다

run()이 resolve_history로 만든 (prev_day, last_run) 중 prev_day만 저장하고
last_run은 버렸다. 프로그램 매매 경로가 승계할 값이 그 last_run이다.

psych_snapshot을 대신 쓸 수 없다 — 바로 다음 줄에서 이번 런의 z로
덮어써지므로 프로그램이 그걸 읽으면 accel = z - 같은 z = 0이 된다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 2: 진단 로그를 실행 경로별로 가른다

**Files:**
- Modify: `src/strategy/simulators/sim1_psych.py:392`
- Test: `tests/test_sim1_program_parity.py` (Task 1에서 생성됨, 추가)

**Interfaces:**
- Consumes: 기존 `sim_diag.append(sim: str, records: list, path: str = None) -> int` (`src/data/sim_diag.py:82`), `sim_diag.month_path(sim, today=None) -> str` (같은 파일 36행)
- Produces: `self.state['exec_path'] == 'program'`이면 진단 행이 `data/sim1_program_diag_YYYY-MM.csv`로, 아니면 기존대로 `data/sim1_diag_YYYY-MM.csv`로 간다. Task 3이 `exec_path`를 세운다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_sim1_program_parity.py` 끝에 추가한다.

```python
# ── Task 2: 진단 로그 경로 분리 ─────────────────────────────
def _diag_files(d):
    return sorted(f for f in os.listdir(d) if f.endswith('.csv'))


def test_paper_path_writes_sim1_diag():
    """플래그가 없으면 기존 파일명 그대로다(현행 보존).

    후보를 반드시 넣어야 한다 — 진단 행이 0개면 sim_diag.append가 파일을
    만들지 않고 바로 반환한다.
    """
    from src.data import sim_diag
    with tempfile.TemporaryDirectory() as d:
        sim = _isolated_sim(d)
        data_dir = os.path.join(d, 'data')
        os.makedirs(data_dir)
        orig = sim_diag.DATA_DIR
        sim_diag.DATA_DIR = data_dir
        try:
            sim.run([_cand('005930', '삼성전자')] + _filler(), current_prices={})
            files = _diag_files(data_dir)
            assert any(f.startswith('sim1_diag_') for f in files), files
            assert not any(f.startswith('sim1_program_diag_') for f in files), files
        finally:
            sim_diag.DATA_DIR = orig


def test_program_path_writes_separate_diag_file():
    """exec_path=program이면 별도 파일로 간다 — 같은 사이클 이중계상 방지."""
    from src.data import sim_diag
    with tempfile.TemporaryDirectory() as d:
        sim = _isolated_sim(d)
        data_dir = os.path.join(d, 'data')
        os.makedirs(data_dir)
        orig = sim_diag.DATA_DIR
        sim_diag.DATA_DIR = data_dir
        try:
            sim.state['exec_path'] = 'program'
            sim.run([_cand('005930', '삼성전자')] + _filler(), current_prices={})
            files = _diag_files(data_dir)
            assert any(f.startswith('sim1_program_diag_') for f in files), files
            assert not any(f.startswith('sim1_diag_') for f in files), files
        finally:
            sim_diag.DATA_DIR = orig


def test_diag_columns_unchanged():
    """컬럼을 늘리면 헤더 회전이 일어나 07-29 수확분이 갈라진다."""
    from src.data import sim_diag
    assert sim_diag.COLUMNS[-1] == 'ignition4'
    assert len(sim_diag.COLUMNS) == 33
```

그리고 파일 상단 헬퍼 근처(`_snap` 정의 아래)에 후보 생성기를 추가한다. `decide_psych`가 횡단면 z를 만들려면 `MIN_SAMPLE` 이상의 표본이 필요하다 — 표본이 모자라면 `_zmap`이 빈 dict를 반환해 진단 행 자체가 나오지 않는다.

```python
def _cand(code, name, posts=300, avg=50, posters=200, likes=600, change='+1.00%'):
    return {'code': code, 'name': name, 'price': 1000, 'amount': 5_000_000_000,
            'recent_posts_count': posts, 'avg_posts': avg, 'unique_posters': posters,
            'total_likes': likes, 'change_rate': change,
            'sparkline_price': [900, 940, 970, 990, 1000],
            'tick_power': 130.0, 'fact_score': 0.5, 'posts': [{'title': '3분기 공시 확인'}]}


def _filler(n=MIN_SAMPLE + 2):
    """횡단면 z 표본. 값에 분산을 준다 — 전부 같으면 표준편차가 0이라
    z가 만들어지지 않고 진단 행이 비어버린다."""
    return [{'code': f'F{i:03d}', 'name': f'중립{i}', 'price': 1000,
             'amount': 2_000_000_000, 'recent_posts_count': 30 + i * 3,
             'avg_posts': 30 + i * 3, 'unique_posters': 24 + i * 2,
             'total_likes': 30 + i * 3, 'change_rate': '+0.50%',
             'sparkline_price': [980, 990, 1000, 1005, 1000], 'tick_power': 130.0,
             'posts': []} for i in range(n)]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_sim1_program_parity.py -v -k "diag"`
Expected: `test_program_path_writes_separate_diag_file`이 FAIL — `sim1_diag_*`만 생기고 `sim1_program_diag_*`는 없다. 나머지 둘은 PASS.

- [ ] **Step 3: 최소 구현**

`src/strategy/simulators/sim1_psych.py`의 `run()` 392행:

```python
        sim_diag.append('sim1', diags)
```

아래로 바꾼다.

```python
        # 프로그램 매매 경로는 별도 파일로 간다. 같은 CSV에 섞이면 같은 사이클·
        # 같은 종목이 2행씩 들어가 분포 분석이 이중계상된다. 진단 키 이름은
        # Sim1이 소유한다 — 매니페스트 id(sim_psych)와 진단 키(sim1)가 다르다.
        sim_diag.append('sim1_program' if self.state.get('exec_path') == 'program' else 'sim1',
                        diags)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_sim1_program_parity.py -v`
Expected: 5 passed

- [ ] **Step 5: 회귀 확인**

Run: `python -m pytest tests/test_sim1_psych.py -v`
Expected: 16 passed

Run: `python scratch/test_sim1_history.py`
Expected: 전부 PASS

- [ ] **Step 6: 커밋**

```bash
git add src/strategy/simulators/sim1_psych.py tests/test_sim1_program_parity.py
git commit -F - << 'EOF'
feat(sim1): 진단 로그를 실행 경로별로 가른다

run()은 페이퍼와 프로그램 양쪽에서 불린다. Sim1이 selected_sim이 되면
같은 사이클·같은 종목이 한 CSV에 2행씩 들어가 분포 분석이 이중계상된다.

컬럼을 늘리는 대신 sim 키를 갈랐다. sim_diag.month_path가 키로 파일명을
만들기 때문에 헤더 회전이 일어나지 않고 07-29 수확분이 쪼개지지 않는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 3: program_trader가 이력 쌍을 스냅샷에 주입한다

**Files:**
- Modify: `src/pipeline/workers/program_trader.py` — 헬퍼 신설(`_make_adapter` 정의 위, 176행 근처), 360-363행, 405-414행
- Test: `tests/test_sim1_program_parity.py` (추가)

**Interfaces:**
- Consumes: Task 1의 `sim.state['psych_last_run']`, Task 2의 `exec_path` 플래그
- Produces: `_psych_carry(paper_state) -> dict` — 승계할 키만 담은 dict를 반환한다. 승계할 게 없으면 빈 dict. 이 함수 외에 외부에서 쓰는 것은 없다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_sim1_program_parity.py` 끝에 추가한다.

```python
# ── Task 3: 승계 + 파리티 ───────────────────────────────────
def _view(prev_day=None, last_run=None, nav=3_000_000):
    return {'portfolio': {}, 'cash': nav, 'initial_cash': 3_000_000, 'nav': nav,
            'cooldown_codes': {}, 'market_index_healthy': True,
            'psych_prev_day': prev_day, 'psych_last_run': last_run}


PARITY_KEYS = ('decision', 'reason', 'd_sov', 'd_hype', 'accel', 'accel_d1',
               'hist_missing', 'hist_days_ago', 'ignition', 'ignition4')


def test_carry_returns_consumed_pair():
    from src.pipeline.workers.program_trader import _psych_carry
    prev = _snap('20260728')
    last = _snap('20260729', z_sov=0.5)
    carry = _psych_carry({'psych_prev_day': prev, 'psych_last_run': last,
                          'psych_snapshot': _snap('20260729', z_sov=9.9)})
    assert carry == {'psych_prev_day': prev, 'psych_snapshot': last}


def test_carry_is_empty_when_state_absent():
    """페이퍼 state가 없거나 dict가 아니면 현행대로 동작한다(예외 없음)."""
    from src.pipeline.workers.program_trader import _psych_carry
    assert _psych_carry(None) == {}
    assert _psych_carry('nope') == {}
    assert _psych_carry({'cash': 100}) == {}


def test_program_path_reproduces_paper_history_terms():
    """파리티의 실제 증명 — 같은 후보·같은 시각에 두 경로의 진단값이 전부 같다."""
    from src.pipeline.workers.program_trader import _psych_carry

    today = '20260729'
    prev_day = _snap('20260728', z_sov=0.2, z_posters=0.3, z_hype=0.1)
    prev_run = _snap(today, z_sov=0.9, z_posters=1.1, z_hype=0.4)
    cands = [_cand('005930', '삼성전자')] + _filler()
    prices = {'005930': 1000}

    # (1) 페이퍼 run()이 하는 일
    p_prev, p_last = resolve_history(prev_day, prev_run, today)
    o1, d1, new_snap = decide_psych(_view(p_prev, p_last), cands, prices,
                                    today=today, hhmm='1030', ts='t')
    # 페이퍼가 state에 써놓는 것 (Task 1 이후)
    paper_state = {'psych_prev_day': p_prev, 'psych_last_run': p_last,
                   'psych_snapshot': new_snap}

    # (2) 프로그램: 승계 → 다시 resolve_history 통과 → 같은 입력
    carry = _psych_carry(paper_state)
    g_prev, g_last = resolve_history(carry['psych_prev_day'], carry['psych_snapshot'], today)
    o2, d2, _ = decide_psych(_view(g_prev, g_last), cands, prices,
                             today=today, hhmm='1030', ts='t')

    assert (g_prev, g_last) == (p_prev, p_last)   # 재승격이 없다
    assert o1 == o2
    for k in PARITY_KEYS:
        assert [x[k] for x in d1] == [x[k] for x in d2], k


def test_carrying_psych_snapshot_would_collapse_accel():
    """기각한 대안 B를 코드로 못 박는다.

    페이퍼가 방금 덮어쓴 psych_snapshot을 승계하면 accel이 전 종목 0이 된다.
    Phase 2에서 accel>0 게이트가 들어가면 프로그램은 영구 무매매가 된다.
    """
    today = '20260729'
    prev_day = _snap('20260728', z_sov=0.2, z_posters=0.3)
    prev_run = _snap(today, z_sov=0.9, z_posters=1.1)
    cands = [_cand('005930', '삼성전자')] + _filler()
    prices = {'005930': 1000}

    p_prev, p_last = resolve_history(prev_day, prev_run, today)
    _, d_paper, new_snap = decide_psych(_view(p_prev, p_last), cands, prices,
                                        today=today, hhmm='1030', ts='t')
    # 잘못된 승계: last_run 대신 방금 쓴 snapshot
    b_prev, b_last = resolve_history(p_prev, new_snap, today)
    _, d_bad, _ = decide_psych(_view(b_prev, b_last), cands, prices,
                               today=today, hhmm='1030', ts='t')

    assert all(x['accel'] == 0 for x in d_bad)
    assert any(x['accel'] != 0 for x in d_paper)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_sim1_program_parity.py -v -k "carry or reproduces or collapse"`
Expected: FAIL — `ImportError: cannot import name '_psych_carry'`

- [ ] **Step 3: 헬퍼를 만든다**

`src/pipeline/workers/program_trader.py`에서 `def _make_adapter(` 정의(176행) **바로 위**에 추가한다.

```python
def _psych_carry(paper_state) -> dict:
    """Sim1 이력 슬롯을 페이퍼 심 state에서 프로그램 스냅샷으로 승계한다.

    페이퍼가 **이번 런에 실제로 소비한** 쌍(psych_prev_day, psych_last_run)을 옮긴다.
    psych_snapshot을 옮기면 안 된다 — 그 값은 페이퍼가 방금 이번 런의 z로 덮어썼기
    때문에 프로그램의 accel이 z - 같은 z = 0이 되어 전 종목 0으로 무너진다.

    psych_last_run은 정의상 None이거나 오늘 날짜다(페이퍼의 resolve_history가 승격을
    이미 끝냈다). 그래서 프로그램 쪽 run()이 다시 resolve_history를 통과해도 재승격이
    일어나지 않는다 — 이 승계는 멱등이다.

    Sim1 외의 심은 이 슬롯이 없어 빈 dict가 나온다(현행 동작 유지).
    """
    if not isinstance(paper_state, dict):
        return {}
    prev_day = paper_state.get('psych_prev_day')
    last_run = paper_state.get('psych_last_run')
    if prev_day is None and last_run is None:
        return {}
    return {'psych_prev_day': prev_day, 'psych_snapshot': last_run}
```

- [ ] **Step 4: 헬퍼 테스트 통과를 확인한다**

Run: `python -m pytest tests/test_sim1_program_parity.py -v -k "carry or reproduces or collapse"`
Expected: 4 passed

- [ ] **Step 5: 스냅샷 구성에 배선한다**

`src/pipeline/workers/program_trader.py` 360-363행:

```python
    # market_index_healthy 게이트는 가상 심 상태(리베로가 기록)에서 승계 — 페이퍼와 동일 동작.
    market_index_healthy = True
    if isinstance(getattr(sim, 'state', None), dict):
        market_index_healthy = bool(sim.state.get('market_index_healthy', True))
```

아래로 바꾼다(`paper_state`를 한 번만 잡아 뒤에서 재사용한다).

```python
    # market_index_healthy 게이트는 가상 심 상태(리베로가 기록)에서 승계 — 페이퍼와 동일 동작.
    # 주의: sim.state는 _make_adapter가 스냅샷으로 갈아끼우기 전까지만 페이퍼 상태다.
    paper_state = getattr(sim, 'state', None)
    market_index_healthy = True
    if isinstance(paper_state, dict):
        market_index_healthy = bool(paper_state.get('market_index_healthy', True))
```

이어서 405-414행의 `snapshot` 딕셔너리 정의:

```python
    snapshot = {
        'cash': max(0.0, effective_budget - invested_cost),
        'invested': invested_cost,
        'portfolio': snapshot_portfolio,
        'total_fees': 0, 'history': [effective_budget], 'daily_trades': [], 'peak_nav': effective_budget,
        'market_index_healthy': market_index_healthy,
        'cooldown_codes': dict(ledger.get('cooldown_codes', {})),  # 손절 쿨다운 영속화
    }
```

닫는 중괄호 **뒤에** 두 줄을 덧붙인다.

```python
    snapshot = {
        'cash': max(0.0, effective_budget - invested_cost),
        'invested': invested_cost,
        'portfolio': snapshot_portfolio,
        'total_fees': 0, 'history': [effective_budget], 'daily_trades': [], 'peak_nav': effective_budget,
        'market_index_healthy': market_index_healthy,
        'cooldown_codes': dict(ledger.get('cooldown_codes', {})),  # 손절 쿨다운 영속화
        'exec_path': 'program',  # 심이 진단 로그를 페이퍼와 분리하도록 알린다
    }
    # 이력 승계(현재 Sim1만 해당). 없으면 아무것도 안 넣는다 = 현행 동작.
    snapshot.update(_psych_carry(paper_state))
```

- [ ] **Step 6: 전체 테스트 통과를 확인한다**

Run: `python -m pytest tests/test_sim1_program_parity.py -v`
Expected: 9 passed

- [ ] **Step 7: 회귀 확인**

Run: `python -m pytest tests/ -q`
Expected: 기존과 동일하게 전부 PASS (실패가 있으면 이 작업 전에도 실패했는지 `git stash`로 확인한다)

Run: `python scratch/test_sim1_history.py`
Expected: 전부 PASS

Run: `python scratch/test_sim_run.py`
Expected: 기존과 동일한 결과. Sim1이 크래시 없이 돌고 진입 동작이 바뀌지 않는다.

- [ ] **Step 8: 커밋**

```bash
git add src/pipeline/workers/program_trader.py tests/test_sim1_program_parity.py
git commit -F - << 'EOF'
feat(program): Sim1 이력 쌍을 페이퍼에서 승계 + 진단 경로 분리

합성 state에 이력 슬롯이 없어 프로그램 런은 항상 hist_missing=1이었다.
Phase 2에서 accel>0 게이트가 들어가면 프로그램 Sim1은 영구 무매매가 된다.

페이퍼가 이번 런에 소비한 (prev_day, last_run)을 그대로 주입한다.
resolve_history가 이 입력에 멱등이라(소비된 last_run은 None이거나 오늘자)
재승격 없이 같은 입력으로 돌아간다. 두 경로의 진단값이 전 종목 일치함을
테스트로 고정했고, psych_snapshot을 대신 승계하면 accel이 무너진다는 것도
함께 못 박았다.

매매 동작은 바뀌지 않는다 — ignition4는 여전히 진입에 쓰이지 않는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## 배포 후 확인 (Sim1이 selected_sim이 된 다음 거래일)

지금 Sim1은 selected_sim이 아니므로 이 변경은 **당장 프로그램 매매 동작을 바꾸지 않는다.** Sim1을 선택한 뒤 확인할 것:

- [ ] `data/sim1_program_diag_YYYY-MM.csv`가 생겼는가
- [ ] `data/sim1_diag_YYYY-MM.csv`에 프로그램 행이 섞이지 않았는가(같은 ts·code가 2행이 아닌가)
- [ ] 프로그램 행의 `hist_missing` 비율이 페이퍼 행과 같은가 (다르면 승계가 안 된 것)
- [ ] 같은 ts의 페이퍼 행과 프로그램 행에서 `d_sov`·`accel`·`ignition4`가 일치하는가

## Self-Review 결과

- **스펙 커버리지**: 설계 1절(psych_last_run 저장) → Task 1. 2절(스냅샷 주입 + 멱등성) → Task 3. 3절(진단 키) → Task 2. 경계 조건(state가 dict 아님) → Task 3 Step 1의 `test_carry_is_empty_when_state_absent`. 기각한 대안 B → Task 3의 `test_carrying_psych_snapshot_would_collapse_accel`. 검증 4항목(멱등성·파리티·진단 분리·회귀) 전부 태스크가 있다.
- **타입 일관성**: `_psych_carry`는 Task 3에서 정의하고 같은 태스크에서만 쓴다. `resolve_history`·`decide_psych`·`MIN_SAMPLE`은 기존 시그니처 그대로. `_snap`/`_cand`/`_filler`/`_view`/`_isolated_sim` 헬퍼는 Task 1·2에서 정의하고 Task 3에서 재사용하므로 **Task 순서대로 실행해야 한다**(Task 3만 단독 실행 불가).
- **알려진 한계**: 파리티 테스트는 `decide_psych`/`resolve_history` 수준에서 두 경로를 재현한다. `run_program_trading` 전체는 GitHub API·KIS 잔고 조회를 타므로 단위 테스트로 덮지 않는다 — 실제 배선은 위 "배포 후 확인"에서 검증한다.
