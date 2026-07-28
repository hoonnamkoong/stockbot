# Sim1 전일 스냅샷 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sim1이 매 런 횡단면 z 스냅샷을 state에 남기고, 전일·직전 런과의 차이(`d_sov`·`d_hype`·`accel`·`accel_d1`)를 계산해 진단 로그에 기록한다. 진입 동작은 바뀌지 않는다.

**Architecture:** 스냅샷은 state 슬롯 2개(`psych_prev_day`·`psych_snapshot`)에 z 스케일로만 저장한다. 직전 런 스냅샷의 날짜가 오늘과 다르면 그것이 곧 전일 마지막 런이므로, 그 사실 하나로 승격이 끝난다(별도 "당일 마지막" 추적 불필요). `decide_psych`는 순수함수를 유지하고, 스냅샷을 인자로 받아 새 스냅샷을 반환값에 실어 보낸다.

**Tech Stack:** Python 3, 표준 라이브러리만. 테스트는 이 저장소 관행대로 `scratch/test_*.py`의 자체 assert 스크립트(`PYTHONPATH=. python scratch/test_x.py`), pytest 아님.

## Global Constraints

- **진입 동작 불변.** 이번 변경으로 기존 3항 `ignition` 값과 진입/청산 결정이 달라지면 안 된다. `ignition4`는 계산·기록만 한다.
- **결측은 중립 0.** 이력 없는 종목은 `d_sov = d_hype = accel = accel_d1 = 0`, `hist_missing = 1`.
- **`hist_days_ago > 5`이면 결측 취급.**
- **09:30 이전에는 `accel = 0`.** 판정 기준은 주입된 시각의 `HHMM` 문자열 비교.
- **저장은 z 스케일만.** 원값(sov·posts·hype)은 스냅샷에 넣지 않는다.
- **날짜·시각은 주입 가능해야 한다.** 순수함수는 `date.today()`를 부르지 않는다 — 백테스트가 실벽시계를 쓰면 롤오버가 영영 안 돈다.
- **`z(d_sov)`·`z(d_hype)`는 이력 있는 종목만으로 계산**하고, 결측 종목에는 0을 준다.
- 파일: `src/strategy/simulators/sim1_psych.py`, `src/data/sim_diag.py`, `scratch/test_sim1_history.py`. 새 모듈은 만들지 않는다(Sim1 전용 로직이라 단일 사용처).

---

### Task 1: sim_diag 컬럼 확장 + 헤더 회전

`sim_diag.append`는 파일이 비었을 때만 헤더를 쓴다. 컬럼을 추가한 뒤 기존 파일이 남아 있으면 열이 조용히 어긋난다. 헤더가 다르면 새 파일로 회전시킨다.

**Files:**
- Modify: `src/data/sim_diag.py`
- Test: `scratch/test_sim1_history.py` (신규 생성, Task 1 몫만)

**Interfaces:**
- Consumes: 없음
- Produces: `sim_diag.COLUMNS`에 8개 컬럼 추가 — `d_sov`, `d_hype`, `accel`, `accel_d1`, `z_hype`, `hist_missing`, `hist_days_ago`, `ignition4`. `sim_diag.append(sim, records, path=None) -> int` 시그니처는 그대로.

- [ ] **Step 1: 실패하는 테스트 작성**

`scratch/test_sim1_history.py` 를 새로 만든다.

```python
"""Sim1 전일 스냅샷 · 진단 로그 확장 단위 테스트 — 네트워크 없음.
실행: PYTHONPATH=. python scratch/test_sim1_history.py

설계: docs/superpowers/specs/2026-07-28-sim1-history-snapshot-design.md
"""
import csv
import os
import sys
import tempfile

sys.path.insert(0, '.')

from src.data import sim_diag

results = []


def check(name, cond):
    results.append((name, cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


# ── Task 1: 진단 로그 컬럼 확장 ────────────────────────────
def test_new_columns_exist():
    need = ['d_sov', 'd_hype', 'accel', 'accel_d1', 'z_hype',
            'hist_missing', 'hist_days_ago', 'ignition4']
    check('신규 컬럼 8개가 COLUMNS에 있다',
          all(c in sim_diag.COLUMNS for c in need))


def test_header_rotation_on_mismatch():
    """헤더가 다른 기존 파일이 있으면 새 파일로 회전한다."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'sim1_diag_2026-07.csv')
        with open(path, 'w', newline='', encoding='utf-8') as f:
            f.write('ts,sim,code\nold,sim1,005930\n')      # 구 헤더
        sim_diag.append('sim1', [{'code': '005930', 'd_sov': '1.5'}], path=path)

        with open(path, encoding='utf-8') as f:
            head = f.readline().strip().split(',')
        check('헤더 불일치 시 기존 파일을 덮지 않는다', head == ['ts', 'sim', 'code'])

        rotated = [n for n in os.listdir(d) if n != os.path.basename(path)]
        check('회전 파일이 생성된다', len(rotated) == 1)
        with open(os.path.join(d, rotated[0]), encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        check('회전 파일에 새 컬럼이 기록된다',
              len(rows) == 1 and rows[0]['d_sov'] == '1.5')


def test_append_still_works_on_fresh_file():
    """기존 동작 회귀: 빈 파일이면 그대로 헤더를 쓴다."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'sim1_diag_2026-07.csv')
        n = sim_diag.append('sim1', [{'code': '005930', 'decision': 'entry'}], path=path)
        with open(path, encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        check('신규 파일에 정상 기록', n == 1 and rows[0]['decision'] == 'entry')


if __name__ == '__main__':
    test_new_columns_exist()
    test_header_rotation_on_mismatch()
    test_append_still_works_on_fresh_file()
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} 통과")
    sys.exit(1 if failed else 0)
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. python scratch/test_sim1_history.py`
Expected: FAIL — `신규 컬럼 8개가 COLUMNS에 있다`, `헤더 불일치 시...` 실패

- [ ] **Step 3: 컬럼 추가**

`src/data/sim_diag.py` 의 `COLUMNS` 끝에 추가한다.

```python
COLUMNS = [
    'ts', 'sim', 'code', 'name',
    'decision',          # entry | skip
    'reason',            # skip 사유 (첫 번째로 걸린 게이트)
    # ── 진입 판단에 쓴 값들 ─────────────────────────────
    'price', 'change_rate', 'amount', 'adx', 'tick_power',
    'posts', 'unique_posters', 'posts_per_poster', 'avg_posts', 'buzz_ratio',
    'total_likes', 'likes_per_post', 'sov', 'z_posters', 'z_sov', 'z_likes',
    'ignition', 'hype_score', 'fact_score',
    # ── 이력 파생 (진입에는 아직 쓰지 않는다. Phase 2 입력) ──
    'z_hype', 'd_sov', 'd_hype', 'accel', 'accel_d1',
    'hist_missing', 'hist_days_ago', 'ignition4',
]
```

- [ ] **Step 4: 헤더 회전 구현**

`append()` 안, `is_new` 판정 부분을 교체한다.

```python
def _rotate_if_stale(path) -> str:
    """기존 파일 헤더가 현재 COLUMNS와 다르면 옆으로 치우고 새 파일을 쓰게 한다.

    append는 빈 파일일 때만 헤더를 쓴다. 컬럼이 늘어난 뒤 옛 파일에 이어 쓰면
    열이 조용히 어긋나 로그 전체가 못 쓰게 된다.
    """
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return path
    try:
        with open(path, encoding='utf-8') as f:
            head = f.readline().strip().lstrip('﻿').split(',')
    except Exception:
        return path
    if head == COLUMNS:
        return path
    base, ext = os.path.splitext(path)
    for i in range(1, 100):
        alt = f"{base}_v{i}{ext}"
        if not os.path.exists(alt):
            return alt
    return path
```

`append()` 본문에서 `path = path or month_path(sim)` 바로 다음 줄에 삽입한다.

```python
        path = path or month_path(sim)
        path = _rotate_if_stale(path)
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
```

- [ ] **Step 5: 통과 확인**

Run: `PYTHONPATH=. python scratch/test_sim1_history.py`
Expected: `3/3 통과` 이상 (체크 5개 전부 PASS)

- [ ] **Step 6: 커밋**

```bash
git add src/data/sim_diag.py scratch/test_sim1_history.py
git commit -F - << 'EOF'
feat(diag): 이력 파생 컬럼 8개 + 헤더 불일치 시 파일 회전

append는 빈 파일일 때만 헤더를 쓴다. 컬럼을 늘린 뒤 옛 파일에 이어 쓰면
열이 조용히 어긋나 그 달 로그 전체가 못 쓰게 된다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 2: 스냅샷 승격 + 파생 3항 계산

핵심 로직. 전부 순수함수이며 `date.today()`를 부르지 않는다.

**Files:**
- Modify: `src/strategy/simulators/sim1_psych.py`
- Test: `scratch/test_sim1_history.py` (Task 1 파일에 이어서 추가)

**Interfaces:**
- Consumes: `sim1_psych._zmap(pairs) -> dict` (기존)
- Produces:
  - `resolve_history(prev_day, snapshot, today) -> (prev_day, last_run)` — 둘 다 dict 또는 None
  - `history_terms(rows, prev_day, last_run, today, hhmm) -> None` — `rows`의 각 dict를 제자리 수정. `d_sov`·`d_hype`·`accel`·`accel_d1`·`hist_missing`·`hist_days_ago`·`ignition4` 키를 채운다.
  - `build_snapshot(rows, today, ts) -> dict` — `{'date': today, 'ts': ts, 'z': {code: {'z_sov','z_posters','z_hype'}}}`
  - 상수 `HIST_MAX_DAYS = 5`, `ACCEL_START_HHMM = '0930'`
  - `rows`의 각 dict는 Task 2 시점부터 `z_hype` 키를 갖는다(`_features`가 채움).

- [ ] **Step 1: 실패하는 테스트 작성**

`scratch/test_sim1_history.py` 의 `if __name__` 블록 **위에** 추가한다.

```python
# ── Task 2: 스냅샷 승격 · 파생 3항 ─────────────────────────
from src.strategy.simulators import sim1_psych as sp


def _snap(date, ts='15:37', **codes):
    """{code: (z_sov, z_posters, z_hype)} → 스냅샷 dict"""
    return {'date': date, 'ts': ts,
            'z': {c: {'z_sov': v[0], 'z_posters': v[1], 'z_hype': v[2]}
                  for c, v in codes.items()}}


def test_promote_on_date_change():
    """직전 런이 어제 것이면 그것이 전일 확정값으로 승격된다."""
    old_prev = _snap('20260724', A=(0.1, 0.1, 0.1))
    yesterday = _snap('20260727', A=(1.0, 1.0, 1.0))
    prev, last = sp.resolve_history(old_prev, yesterday, '20260728')
    check('날짜가 바뀌면 직전 런이 prev_day로 승격', prev is yesterday)
    check('그날 첫 런에는 직전 런이 없다', last is None)


def test_no_promote_same_day():
    """같은 날 두 번째 런에서는 prev_day가 유지된다."""
    prev_day = _snap('20260727', A=(1.0, 1.0, 1.0))
    same_day = _snap('20260728', ts='10:21', A=(2.0, 2.0, 2.0))
    prev, last = sp.resolve_history(prev_day, same_day, '20260728')
    check('같은 날엔 prev_day 유지', prev is prev_day)
    check('같은 날엔 직전 런이 살아 있다', last is same_day)


def test_first_ever_run():
    prev, last = sp.resolve_history(None, None, '20260728')
    check('이력이 아예 없으면 둘 다 None', prev is None and last is None)


def test_derived_terms_basic():
    prev_day = _snap('20260727', A=(1.0, 0.5, 0.2))
    last_run = _snap('20260728', ts='10:21', A=(1.4, 0.9, 0.3))
    rows = [{'code': 'A', 'z_sov': 1.5, 'z_posters': 1.2, 'z_hype': 0.6, 'z_likes': 0.4}]
    sp.history_terms(rows, prev_day, last_run, '20260728', '1030')
    r = rows[0]
    check('d_sov = 오늘 − 전일', abs(r['d_sov'] - 0.5) < 1e-9)
    check('d_hype = 오늘 − 전일', abs(r['d_hype'] - 0.4) < 1e-9)
    check('accel = 오늘 − 직전 런', abs(r['accel'] - 0.3) < 1e-9)
    check('accel_d1 = 오늘 − 전일', abs(r['accel_d1'] - 0.7) < 1e-9)
    check('이력 있으면 hist_missing=0', r['hist_missing'] == 0)
    check('hist_days_ago = 1', r['hist_days_ago'] == 1)


def test_missing_history_is_neutral_zero():
    prev_day = _snap('20260727', A=(1.0, 0.5, 0.2))
    rows = [{'code': 'B', 'z_sov': 1.5, 'z_posters': 1.2, 'z_hype': 0.6, 'z_likes': 0.4}]
    sp.history_terms(rows, prev_day, None, '20260728', '1030')
    r = rows[0]
    check('신규 유입은 d_sov=0', r['d_sov'] == 0)
    check('신규 유입은 d_hype=0', r['d_hype'] == 0)
    check('신규 유입은 hist_missing=1', r['hist_missing'] == 1)


def test_stale_history_treated_missing():
    """5일 초과 이력은 '전일'이라 부를 수 없다."""
    prev_day = _snap('20260720', A=(1.0, 0.5, 0.2))
    rows = [{'code': 'A', 'z_sov': 1.5, 'z_posters': 1.2, 'z_hype': 0.6, 'z_likes': 0.4}]
    sp.history_terms(rows, prev_day, None, '20260728', '1030')
    check('8일 전 이력은 결측 취급', rows[0]['hist_missing'] == 1 and rows[0]['d_sov'] == 0)
    check('hist_days_ago는 그대로 기록', rows[0]['hist_days_ago'] == 8)


def test_accel_suppressed_before_0930():
    prev_day = _snap('20260727', A=(1.0, 0.5, 0.2))
    last_run = _snap('20260728', ts='09:15', A=(1.4, 0.9, 0.3))
    rows = [{'code': 'A', 'z_sov': 1.5, 'z_posters': 1.2, 'z_hype': 0.6, 'z_likes': 0.4}]
    sp.history_terms(rows, prev_day, last_run, '20260728', '0915')
    check('09:30 이전 accel=0', rows[0]['accel'] == 0)
    check('09:30 이전에도 accel_d1은 계산', abs(rows[0]['accel_d1'] - 0.7) < 1e-9)

    rows2 = [{'code': 'A', 'z_sov': 1.5, 'z_posters': 1.2, 'z_hype': 0.6, 'z_likes': 0.4}]
    sp.history_terms(rows2, prev_day, last_run, '20260728', '0930')
    check('09:30부터 accel 정상', abs(rows2[0]['accel'] - 0.3) < 1e-9)


def test_delta_z_excludes_missing():
    """z(d_sov)는 이력 있는 종목만으로 계산한다.

    결측 종목의 0을 분포에 넣으면 z가 왜곡된다. 이력 종목 10개(_zmap의
    MIN_SAMPLE)의 d_sov가 전부 같으면 분산 0이라 z는 만들어지지 않고,
    ignition4는 z(d_sov) 항 없이 계산된다.
    """
    codes = {f"H{i}": (1.0, 0.5, 0.2) for i in range(10)}
    prev_day = _snap('20260727', **codes)
    rows = [{'code': f"H{i}", 'z_sov': 2.0, 'z_posters': 1.0,
             'z_hype': 0.7, 'z_likes': 0.4} for i in range(10)]
    rows.append({'code': 'NEW', 'z_sov': 2.0, 'z_posters': 1.0,
                 'z_hype': 0.7, 'z_likes': 0.4})
    sp.history_terms(rows, prev_day, None, '20260728', '1030')
    new_row = rows[-1]
    check('결측 종목의 d_sov는 0', new_row['d_sov'] == 0)
    check('이력 종목의 d_sov는 1.0', abs(rows[0]['d_sov'] - 1.0) < 1e-9)
    check('모든 행에 ignition4가 있다', all('ignition4' in r for r in rows))


def test_build_snapshot():
    rows = [{'code': 'A', 'z_sov': 1.5, 'z_posters': 1.2, 'z_hype': 0.6},
            {'code': 'B', 'z_sov': None, 'z_posters': 0.3, 'z_hype': 0.1}]
    snap = sp.build_snapshot(rows, '20260728', '2026-07-28 10:30:00')
    check('스냅샷 날짜', snap['date'] == '20260728')
    check('스냅샷에 z만 담긴다', set(snap['z']['A']) == {'z_sov', 'z_posters', 'z_hype'})
    check('z가 None인 종목은 담지 않는다', 'B' not in snap['z'])
```

`if __name__` 블록의 호출 목록에도 추가한다.

```python
    test_promote_on_date_change()
    test_no_promote_same_day()
    test_first_ever_run()
    test_derived_terms_basic()
    test_missing_history_is_neutral_zero()
    test_stale_history_treated_missing()
    test_accel_suppressed_before_0930()
    test_delta_z_excludes_missing()
    test_build_snapshot()
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. python scratch/test_sim1_history.py`
Expected: FAIL — `AttributeError: module ... has no attribute 'resolve_history'`

- [ ] **Step 3: 구현**

`src/strategy/simulators/sim1_psych.py` 의 `_zmap` 아래에 추가한다.

```python
HIST_MAX_DAYS = 5            # 주말 낀 연휴(금~화)까지는 '전일'로 인정한다
ACCEL_START_HHMM = '0930'    # 개장 30분은 z가 90분위 2.46z로 요동한다(실측)


def resolve_history(prev_day, snapshot, today):
    """(prev_day, last_run) 결정. 순수함수.

    직전 런 스냅샷의 날짜가 오늘이 아니면 그것이 곧 전일 마지막 런이다.
    이 사실 하나로 승격이 끝나므로 '당일 마지막'을 따로 추적할 필요가 없다.
    """
    if snapshot and snapshot.get('date') != today:
        return snapshot, None
    return prev_day, snapshot


def _days_between(older, newer):
    """'YYYYMMDD' 두 개의 일수 차. 못 읽으면 None."""
    from datetime import datetime
    try:
        a = datetime.strptime(str(older), '%Y%m%d')
        b = datetime.strptime(str(newer), '%Y%m%d')
    except (ValueError, TypeError):
        return None
    return (b - a).days


def history_terms(rows, prev_day, last_run, today, hhmm):
    """rows에 이력 파생값을 제자리로 채운다.

    결측은 중립 0이다. 매일 후보의 38~48%가 신규 유입이라(실측) 이건
    예외 처리가 아니라 절반의 정책이다. fail-closed는 Sim1이 노리는
    '새로 터진 관심'을 구조적으로 배제한다.
    """
    pz = (prev_day or {}).get('z', {})
    lz = (last_run or {}).get('z', {})
    days_ago = _days_between((prev_day or {}).get('date'), today)
    usable = bool(pz) and days_ago is not None and 0 < days_ago <= HIST_MAX_DAYS
    accel_ok = str(hhmm) >= ACCEL_START_HHMM

    raw = {}
    for r in rows:
        c = r['code']
        p = pz.get(c) if usable else None
        r['hist_days_ago'] = days_ago if days_ago is not None else ''
        r['hist_missing'] = 0 if p else 1
        if p:
            raw[c] = (r.get('z_sov', 0) - p['z_sov'], r.get('z_hype', 0) - p['z_hype'])
            r['accel_d1'] = r.get('z_posters', 0) - p['z_posters']
        else:
            r['accel_d1'] = 0

        l = lz.get(c)
        r['accel'] = (r.get('z_posters', 0) - l['z_posters']) if (l and accel_ok) else 0

    # 델타의 횡단면 z는 이력 있는 종목만으로 만든다.
    # 결측의 0을 분포에 넣으면 z가 왜곡된다.
    zd_sov = _zmap([(c, v[0]) for c, v in raw.items()])
    zd_hype = _zmap([(c, v[1]) for c, v in raw.items()])
    for r in rows:
        c = r['code']
        r['d_sov'] = raw[c][0] if c in raw else 0
        r['d_hype'] = raw[c][1] if c in raw else 0
        # 설계식 4항. 계산만 하고 진입에는 쓰지 않는다 — 3항과 나란히
        # 기록해 다음 거래일 로그로 분포·통과율을 비교하기 위한 값이다.
        parts = [1.0 * (r.get('z_posters') or 0),
                 1.0 * zd_sov.get(c, 0),
                 0.7 * zd_hype.get(c, 0),
                 0.5 * (r.get('z_likes') or 0)]
        r['ignition4'] = sum(parts)


def build_snapshot(rows, today, ts):
    """이번 런의 z를 스냅샷으로. z 스케일만 담는다 — 원값은 당일 누적이라
    오전에 60~77% 어긋난다(실측)."""
    z = {}
    for r in rows:
        if r.get('z_sov') is None or r.get('z_posters') is None or r.get('z_hype') is None:
            continue
        z[r['code']] = {'z_sov': r['z_sov'], 'z_posters': r['z_posters'],
                        'z_hype': r['z_hype']}
    return {'date': today, 'ts': ts, 'z': z}
```

- [ ] **Step 4: `_features`가 `z_hype`를 채우게 한다**

`_features()` 안, `z_likes` 계산 다음 줄에 추가하고 배정 루프에도 넣는다.

```python
    z_posters = _zmap([(r['code'], r['posters']) for r in rows])
    z_sov = _zmap([(r['code'], r['sov']) for r in rows])
    z_likes = _zmap([(r['code'], r['likes_per_post']) for r in rows])
    z_hype = _zmap([(r['code'], r['hype']) for r in rows])
    feat = {}
    for r in rows:
        c = r['code']
        r['z_posters'] = z_posters.get(c)
        r['z_sov'] = z_sov.get(c)
        r['z_likes'] = z_likes.get(c)
        r['z_hype'] = z_hype.get(c)
```

`hype_score`는 0~1 고정 스케일이지만 시간대 안정성이 검증되지 않았다. sov와 같은 처리를 받게 한다.

- [ ] **Step 5: 통과 확인**

Run: `PYTHONPATH=. python scratch/test_sim1_history.py`
Expected: 전체 PASS (Task 1의 5개 + Task 2의 20개)

- [ ] **Step 6: 커밋**

```bash
git add src/strategy/simulators/sim1_psych.py scratch/test_sim1_history.py
git commit -F - << 'EOF'
feat(sim1): 전일 스냅샷 승격 + d_sov·accel·d_hype 계산

직전 런 스냅샷의 날짜가 오늘이 아니면 그것이 곧 전일 마지막 런이다.
이 사실 하나로 승격이 끝나므로 '당일 마지막'을 따로 추적하지 않는다.

결측은 중립 0. 매일 후보의 38~48%가 신규 유입이라 예외가 아니라
절반의 정책이다. 델타의 횡단면 z는 이력 있는 종목만으로 만든다 —
결측의 0을 분포에 넣으면 z가 왜곡된다.

날짜·시각은 인자로 받는다. 순수함수가 date.today()를 부르면
백테스트에서 롤오버가 영영 돌지 않는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 3: decide_psych · run 배선 + 진입 불변 회귀

**Files:**
- Modify: `src/strategy/simulators/sim1_psych.py` (`decide_psych`, `PsychDivergenceSimulator.run`)
- Test: `scratch/test_sim1_history.py` (이어서 추가)

**Interfaces:**
- Consumes: Task 2의 `resolve_history`·`history_terms`·`build_snapshot`
- Produces: `decide_psych(view, candidates, current_prices, today=None, hhmm=None, ts=None) -> (orders, diags, snapshot)` — **3-tuple로 변경**. `view`에 `psych_prev_day`·`psych_last_run` 키가 추가되며, **둘 다 `run()`이 `resolve_history`로 이미 판정한 결과**다. 승격 판정은 `run()` 한 곳에만 둔다 — 두 곳에 두면 갈라진다. 직접 호출자는 없고(전부 `PsychDivergenceSimulator` 경유) `run()`만 맞추면 된다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# ── Task 3: 배선 + 진입 불변 회귀 ──────────────────────────
def _cand(code, posts, posters, likes, price=10000, change='+1.00%'):
    return {'code': code, 'name': code, 'price': price, 'amount': 5_000_000_000,
            'recent_posts_count': posts, 'unique_posters': posters,
            'total_likes': likes, 'avg_posts': 10, 'change_rate': change,
            'sparkline_price': [price] * 5, 'tick_power': 200, 'posts': []}


def _view(**kw):
    v = {'portfolio': {}, 'cash': 3000000, 'initial_cash': 3000000,
         'nav': 3000000, 'cooldown_codes': {}, 'market_index_healthy': True,
         'psych_prev_day': None, 'psych_last_run': None}
    v.update(kw)
    return v


def test_decide_returns_snapshot():
    cands = [_cand(f"{i:06d}", 50 + i * 7, 20 + i, 100 + i * 5) for i in range(12)]
    prices = {c['code']: c['price'] for c in cands}
    orders, diags, snap = sp.decide_psych(_view(), cands, prices,
                                          today='20260728', hhmm='1030',
                                          ts='2026-07-28 10:30:00')
    check('3-tuple 반환', isinstance(snap, dict) and 'z' in snap)
    check('스냅샷 날짜가 주입값', snap['date'] == '20260728')
    check('diag에 이력 컬럼이 실린다',
          all('d_sov' in d and 'ignition4' in d and 'hist_missing' in d for d in diags))


def test_entry_decisions_unchanged_by_history():
    """★ 진입 불변 회귀 — 이력이 있든 없든 진입/청산 결정이 같아야 한다.

    이번 변경은 기록만 한다. ignition(3항)과 decision이 달라지면 실패다.
    """
    cands = [_cand(f"{i:06d}", 50 + i * 7, 20 + i, 100 + i * 5) for i in range(12)]
    prices = {c['code']: c['price'] for c in cands}

    o1, d1, snap1 = sp.decide_psych(_view(), cands, prices, today='20260728',
                                    hhmm='1030', ts='t1')
    prev = {'date': '20260727', 'ts': 't0',
            'z': {c['code']: {'z_sov': -2.0, 'z_posters': -2.0, 'z_hype': -2.0}
                  for c in cands}}
    o2, d2, _ = sp.decide_psych(_view(psych_prev_day=prev, psych_last_run=prev),
                                cands, prices, today='20260728',
                                hhmm='1030', ts='t1')

    check('주문이 동일', o1 == o2)
    check('진입 결정이 동일', [d['decision'] for d in d1] == [d['decision'] for d in d2])
    check('skip 사유가 동일', [d['reason'] for d in d1] == [d['reason'] for d in d2])
    check('3항 ignition이 동일',
          [d['ignition'] for d in d1] == [d['ignition'] for d in d2])
    check('이력이 붙으면 d_sov는 달라진다(계산은 되고 있다)',
          any(d['d_sov'] != 0 for d in d2))
```

`if __name__` 호출 목록에 추가한다.

```python
    test_decide_returns_snapshot()
    test_entry_decisions_unchanged_by_history()
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=. python scratch/test_sim1_history.py`
Expected: FAIL — `decide_psych`가 2-tuple을 반환해 언패킹 에러

- [ ] **Step 3: `decide_psych` 배선**

시그니처와 첫 줄들을 바꾼다.

```python
def decide_psych(view, candidates, current_prices, today=None, hhmm=None, ts=None):
    """[Sim1] 심리 괴리형 결정. (orders, diags, snapshot) 반환. 순수 함수.

    today·hhmm·ts는 주입받는다. 순수함수가 date.today()를 부르면
    백테스트에서 스냅샷 롤오버가 영영 돌지 않는다.
    """
    orders, diags = [], []
    portfolio = view['portfolio']
    sold = set()
    cand_by_code = {s.get('code'): s for s in candidates if s.get('code')}
    feat = _features(candidates)

    rows = list(feat.values())
    # 승격 판정은 run()이 이미 끝냈다. 여기서 다시 해석하지 않는다.
    history_terms(rows, view.get('psych_prev_day'), view.get('psych_last_run'),
                  today, hhmm)
    snapshot = build_snapshot(rows, today, ts)
```

진단 dict `d` 에 이력 값을 싣는다. `'fact_score': stock.get('fact_score', 0),` 다음 줄에 추가한다.

```python
            'fact_score': stock.get('fact_score', 0),
            'z_hype': _fmt(f.get('z_hype')),
            'd_sov': _fmt(f.get('d_sov')), 'd_hype': _fmt(f.get('d_hype')),
            'accel': _fmt(f.get('accel')), 'accel_d1': _fmt(f.get('accel_d1')),
            'hist_missing': f.get('hist_missing', 1),
            'hist_days_ago': f.get('hist_days_ago', ''),
            'ignition4': _fmt(f.get('ignition4')),
```

두 `return orders, diags` 를 전부 바꾼다 (조기 반환 1개 + 말미 1개).

```python
    if not view['market_index_healthy']:
        return orders, diags, snapshot
```

```python
    return orders, diags, snapshot
```

- [ ] **Step 4: `_view` 확장과 `run` 배선**

`sim1_psych.py` 의 `run()` 을 바꾼다. `_view()`는 base에 있고 다른 심이 공유하므로 **건드리지 않고**, Sim1에서 키를 얹는다.

```python
    def run(self, candidates, current_prices=None):
        from datetime import datetime, timedelta, timezone
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)

        now = datetime.now(timezone(timedelta(hours=9)))
        today = now.strftime('%Y%m%d')

        # 승격은 여기 한 곳에서만 판정한다.
        prev_day, last_run = resolve_history(self.state.get('psych_prev_day'),
                                             self.state.get('psych_snapshot'),
                                             today)
        view = self._view(current_prices)
        view['psych_prev_day'] = prev_day
        view['psych_last_run'] = last_run

        orders, diags, snapshot = decide_psych(
            view, candidates, current_prices,
            today=today, hhmm=now.strftime('%H%M'),
            ts=now.strftime('%Y-%m-%d %H:%M:%S'))

        self.state['psych_prev_day'] = prev_day
        self.state['psych_snapshot'] = snapshot

        self._apply(orders, current_prices)
        sim_diag.append('sim1', diags)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
```

- [ ] **Step 5: 통과 확인**

Run: `PYTHONPATH=. python scratch/test_sim1_history.py`
Expected: 전체 PASS

- [ ] **Step 6: 기존 Sim 테스트 회귀 확인**

Run: `PYTHONPATH=. python scratch/test_sim_run.py`
Expected: 기존과 동일한 결과. Sim1이 크래시 없이 돌고 진입 동작이 바뀌지 않았는지 본다. 실패하면 Task 3을 되돌린다.

- [ ] **Step 7: 커밋**

```bash
git add src/strategy/simulators/sim1_psych.py scratch/test_sim1_history.py
git commit -F - << 'EOF'
feat(sim1): 스냅샷 배선 — 진입식은 그대로 두고 기록만 시작한다

decide_psych가 (orders, diags, snapshot) 3-tuple을 반환하고 run()이
state에 저장한다. 직접 호출자는 없어(전부 시뮬레이터 클래스 경유)
호출부 변경은 run() 하나다.

4항 ignition4는 계산해서 3항과 나란히 diag에 남기기만 한다. 지금
진입식에 넣으면 이력 도입과 임계값 변경이 한 번에 섞여 원인을 분리할
수 없다 — Sim1이 6개월간 실패 원인을 몰랐던 상태가 그것이었다.

회귀 테스트로 이력 유무가 주문·진입 결정·3항 ignition을 바꾸지
않음을 고정했다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## 배포 후 확인 (다음 거래일)

코드 배포만으로 동작한다. 2026-07-29 장중 첫 런 이후 db-data에서 확인한다.

- [ ] `data/sim1_diag_2026-07.csv` 에 새 컬럼 8개가 있는가 (없으면 헤더 회전이 `_v1` 파일을 만들었는지 확인)
- [ ] 그날 첫 런에서 `hist_missing`이 전부 1인가 (전일 스냅샷이 아직 없으므로 정상)
- [ ] 둘째 날(07-30)부터 `hist_missing` 비율이 실측 회전율 38~48%와 맞는가
- [ ] `data/sim_psych_state.json` 에 `psych_prev_day`·`psych_snapshot`이 있고 `z`만 담겨 있는가
- [ ] `ignition`(3항)과 `ignition4`의 분포·통과율 차이 → Phase 2 임계값 결정 입력

## Self-Review 결과

- **스펙 커버리지**: 저장 구조(Task 2·3), z 스케일 저장(Task 2 `build_snapshot`), 파생 4개(Task 2), 결측 중립 0(Task 2), 5일 초과(Task 2), 09:30 accel 억제(Task 2), `z_hype`(Task 2 Step 4), diag 8컬럼(Task 1), 헤더 회전(Task 1), `z(d_sov)` 결측 제외(Task 2), 진입 불변(Task 3 회귀 테스트) — 스펙의 검증 항목 7개 전부 테스트가 있다.
- **타입 일관성**: `resolve_history`는 Task 2에서 정의하고 Task 3의 `run()`에서 같은 이름·인자로 재사용한다. `_fmt`는 기존 함수를 그대로 쓴다(`None` → `''`). `hist_missing`·`hist_days_ago`는 포맷하지 않고 정수로 넣는다(`_fmt`는 float 전용).
- **알려진 한계**: 백테스트(`backtest_csv_monthly.py` 등)는 `run()`을 통해 실벽시계 날짜를 받으므로 스냅샷 롤오버가 돌지 않는다. 순수함수는 주입을 받게 만들어 뒀으니 Phase 2에서 백테스트가 시뮬 날짜를 넘기도록 배선하면 된다. 이번 스코프 밖.
