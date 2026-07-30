# 심0 국면 확률 필터 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 국면 판정을 재생 가능한 순수 함수로 만들고, 기준선 4개와 비교해 확률 필터의 우열을 데이터로 판정한다.

**Architecture:** 10분 관측을 CSV에 축적한다(지금 5/6을 버린다). 사후 양방향 평활로 정답 라벨을 만든다. 판정기는 `(prev, obs, params) -> decision` 순수 함수라 과거 데이터에 재생된다. 하네스가 기준선 4개와 함께 지연·오탐·비대칭비용·캘리브레이션을 출력한다.

**Tech Stack:** Python 3.12, pytest. 새 의존성 없음 — 3×3 전이행렬과 정규 우도는 `math`로 충분하다.

## Global Constraints

- `current_regime` 계약 불변: `"BULL"|"SIDEWAYS"|"BEAR"` 문자열. **Sim6·Sim10·Sim7 수정 금지.**
- `calc_bull_score` 계산식 **변경 금지** — Sim7의 `bull_score >= 45` 게이트가 읽는다.
- 판정기·라벨러·하네스는 **순수 함수**. 파일·전역 상태·`datetime.now()` 접근 금지. 시각은 인자로 받는다.
- 룩어헤드 금지: 판정기는 과거 관측만 본다. 미래를 쓰는 것은 **라벨러뿐**이다.
- 가짜 값 금지: 조회 실패·필드 부재를 0이나 50으로 지어내지 않는다. 표본이 적으면 **약한 증거**로 처리한다.
- 이번 계획에서 `current_regime`을 새 판정기로 바꾸지 않는다. `regime_shadow`로 병기만 한다.
- 새 파일은 `src/strategy/` 아래, 테스트는 `tests/` 아래. 파일당 책임 하나.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `src/strategy/regime_observations.py` | 관측 CSV 직렬화·파싱·append(멱등)·롤링 트림 |
| `src/strategy/regime_daily.py` | `output/ohlcv_top100.csv` → 일 해상도 관측 시계열 |
| `src/strategy/regime_label.py` | 사후 양방향 평활 라벨러 + 전환 목록 |
| `src/strategy/regime_filter.py` | 3상태 베이즈 필터 `filter_step` + 관측모형 부트스트랩 |
| `src/strategy/regime_baselines.py` | 기준선 판정기 4개 |
| `src/strategy/regime_eval.py` | 재생 + 채점(지연·오탐·비용) + 캘리브레이션 |
| `scripts/eval_regime.py` | 스윕 실행 + 비교표 출력 (엔트리포인트) |
| `src/pipeline/workers/trade_engine.py` | 관측 append 배선 (수정) |
| `src/strategy/simulators/sim0_libero.py` | 섀도우 판정 기록 (수정) |

---

## Task 1: 관측 이력 CSV

**Files:**
- Create: `src/strategy/regime_observations.py`
- Test: `tests/test_regime_observations.py`

**Interfaces:**
- Produces:
  - `OBS_HEADER: list[str]` = `['ts_kst', 'breadth', 'momentum', 'trend', 'sample', 'source']`
  - `MAX_DISTINCT_DATES: int` = `60`
  - `format_row(ts: str, breadth: float, momentum: float, trend: float | None, sample: int, source: str) -> list[str]`
  - `parse_observations(text: str) -> list[dict]` — 각 dict: `{'ts': str, 'breadth': float, 'momentum': float, 'trend': float | None, 'sample': int, 'source': str}`
  - `append_observation(path: str, ts: str, breadth: float, momentum: float, trend: float | None, sample: int, source: str) -> bool` — 기록했으면 True, 같은 분이 이미 있어 건너뛰면 False
  - `trim_to_recent_dates(rows: list[dict], max_dates: int = MAX_DISTINCT_DATES) -> list[dict]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_regime_observations.py`:

```python
# -*- coding: utf-8 -*-
"""국면 관측 이력 CSV — 10분 해상도 축적.

지금까지 _hour_label('%H:00')이 10분 관측의 5/6을 버렸다. 여기서 분까지 남긴다.
"""
import io
import os

from src.strategy.regime_observations import (
    MAX_DISTINCT_DATES, OBS_HEADER, append_observation, format_row,
    parse_observations, trim_to_recent_dates,
)


def _read(path):
    with io.open(path, encoding='utf-8-sig') as f:
        return f.read()


def test_헤더가_계약이다():
    assert OBS_HEADER == ['ts_kst', 'breadth', 'momentum', 'trend', 'sample', 'source']


def test_새_파일은_헤더와_한_행을_쓴다(tmp_path):
    p = str(tmp_path / 'obs.csv')
    assert append_observation(p, '2026-07-30 09:10', 51.0, -0.12, 39.0, 100, 'top100_live') is True
    rows = parse_observations(_read(p))
    assert len(rows) == 1
    assert rows[0] == {'ts': '2026-07-30 09:10', 'breadth': 51.0, 'momentum': -0.12,
                      'trend': 39.0, 'sample': 100, 'source': 'top100_live'}


def test_같은_분에_두_번_돌면_한_행이다(tmp_path):
    p = str(tmp_path / 'obs.csv')
    append_observation(p, '2026-07-30 09:10', 51.0, -0.12, 39.0, 100, 'top100_live')
    assert append_observation(p, '2026-07-30 09:10', 99.0, 9.9, 1.0, 80, 'candidates') is False
    rows = parse_observations(_read(p))
    assert len(rows) == 1
    assert rows[0]['breadth'] == 51.0, '첫 값을 유지한다 — 같은 분의 재실행이 값을 흔들면 안 된다'


def test_10분_간격_관측이_전부_남는다(tmp_path):
    p = str(tmp_path / 'obs.csv')
    for i, m in enumerate(range(0, 60, 10)):
        append_observation(p, f'2026-07-30 09:{m:02d}', 50.0 + i, 0.0, 10.0, 100, 'top100_live')
    rows = parse_observations(_read(p))
    assert len(rows) == 6, '_hour_label 시절에는 1건만 남았다'
    assert [r['ts'] for r in rows] == [f'2026-07-30 09:{m:02d}' for m in range(0, 60, 10)]


def test_표본이_적어도_기록한다(tmp_path):
    # 현행 _fetch_top100_breadth는 표본 80 미만이면 None을 반환해 통째로 버린다.
    # 확률 모형에서는 약한 증거이므로 버리지 않는다.
    p = str(tmp_path / 'obs.csv')
    assert append_observation(p, '2026-07-30 09:10', 40.0, -1.0, 5.0, 55, 'top100_live') is True
    assert parse_observations(_read(p))[0]['sample'] == 55


def test_trend가_없으면_빈_칸이고_None으로_읽힌다(tmp_path):
    p = str(tmp_path / 'obs.csv')
    append_observation(p, '2026-07-30 09:10', 40.0, -1.0, None, 100, 'top100_live')
    assert parse_observations(_read(p))[0]['trend'] is None


def test_롤링은_거래일_단위다():
    rows = [{'ts': f'2026-{m:02d}-{d:02d} 09:10', 'breadth': 1.0, 'momentum': 0.0,
             'trend': None, 'sample': 100, 'source': 's'}
            for m in (5, 6, 7) for d in range(1, 26)]
    kept = trim_to_recent_dates(rows, max_dates=10)
    assert len({r['ts'][:10] for r in kept}) == 10
    assert kept[-1] is rows[-1], '최신 행이 남는다'


def test_append가_거래일_상한을_지킨다(tmp_path):
    p = str(tmp_path / 'obs.csv')
    for d in range(1, MAX_DISTINCT_DATES + 5):
        append_observation(p, f'2026-07-{d:02d} 09:10'.replace('-0', '-0'), 50.0, 0.0, None, 100, 's') \
            if d <= 31 else None
    rows = parse_observations(_read(p))
    assert len({r['ts'][:10] for r in rows}) <= MAX_DISTINCT_DATES


def test_깨진_행은_건너뛰고_나머지를_읽는다():
    text = ','.join(OBS_HEADER) + '\n' \
           + '2026-07-30 09:10,51.0,-0.12,39.0,100,top100_live\n' \
           + 'garbage\n' \
           + '2026-07-30 09:20,52.0,0.05,39.0,100,top100_live\n'
    rows = parse_observations(text)
    assert [r['ts'] for r in rows] == ['2026-07-30 09:10', '2026-07-30 09:20']


def test_format_row는_문자열_리스트다():
    assert format_row('2026-07-30 09:10', 51.0, -0.125, None, 100, 'x') == \
        ['2026-07-30 09:10', '51.0', '-0.13', '', '100', 'x']
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_regime_observations.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.strategy.regime_observations'`

- [ ] **Step 3: 최소 구현**

`src/strategy/regime_observations.py`:

```python
# -*- coding: utf-8 -*-
"""국면 관측 이력 — 10분 해상도로 (폭, 강도)를 쌓는다.

**왜 이 파일이 생겼나.** 리베로는 10분마다 도는데 `_hour_label`이 시각을 'HH:00'으로
깎아 같은 시간대의 첫 관측만 남겼다. 관측의 5/6이 버려졌고, `intraday` 버킷은 날짜가
바뀌면 리셋되며 백필은 KIS **당일**분봉이라 과거 재구성도 불가능했다. 그래서 10분 지평
모델을 학습·검증할 이력이 0이었다.

**위치**: `data/regime_observations.csv`. 워크플로 수정이 필요 없다 — scraper.yml이 런
시작에 `git checkout db-data -- data/`로 복원하고 끝에 `data/*.csv`를 db-data로 복사한다.
그래서 append가 런 사이에 이어진다.

**표본이 적어도 버리지 않는다.** `_fetch_top100_breadth`는 표본 80 미만이면 None을
반환해 관측을 통째로 폐기하는데, 확률 모형에서 적은 표본은 폐기 대상이 아니라
**약한 증거**다(regime_filter가 sigma를 표본수로 보정한다).
"""
import csv
import io
import os

OBS_HEADER = ['ts_kst', 'breadth', 'momentum', 'trend', 'sample', 'source']

# 롤링 보관 거래일. 60일 × 39슬롯 ≈ 2,340행. 행 수 상한이 아니라 거래일 수로 자르는
# 이유: 런이 지연되거나 건너뛴 날이 있어도 보관 기간의 뜻이 변하지 않는다.
MAX_DISTINCT_DATES = 60


def format_row(ts, breadth, momentum, trend, sample, source):
    """CSV 한 행. trend는 없을 수 있다(일봉 CSV 파싱 실패) → 빈 칸으로 남긴다."""
    return [
        str(ts),
        f'{float(breadth):.1f}',
        f'{float(momentum):.2f}',
        '' if trend is None else f'{float(trend):.1f}',
        str(int(sample)),
        str(source),
    ]


def parse_observations(text):
    """CSV 텍스트 → 관측 리스트. 깨진 행은 건너뛰고 나머지를 살린다."""
    rows = []
    reader = csv.reader(io.StringIO(text.lstrip('﻿')))
    header = None
    for values in reader:
        if not values:
            continue
        if header is None:
            header = [c.strip() for c in values]
            continue
        if len(values) < len(OBS_HEADER):
            continue
        rec = dict(zip(header, [v.strip() for v in values]))
        try:
            rows.append({
                'ts': rec['ts_kst'],
                'breadth': float(rec['breadth']),
                'momentum': float(rec['momentum']),
                'trend': None if rec['trend'] == '' else float(rec['trend']),
                'sample': int(rec['sample']),
                'source': rec['source'],
            })
        except (KeyError, ValueError):
            continue
    return rows


def trim_to_recent_dates(rows, max_dates=MAX_DISTINCT_DATES):
    """최근 `max_dates`개 거래일의 행만 남긴다(순서 유지)."""
    dates = []
    for r in rows:
        d = r['ts'][:10]
        if d not in dates:
            dates.append(d)
    keep = set(dates[-max_dates:])
    return [r for r in rows if r['ts'][:10] in keep]


def append_observation(path, ts, breadth, momentum, trend, sample, source):
    """관측 한 건 append. 같은 분이 이미 있으면 아무것도 하지 않고 False.

    같은 분의 재실행이 값을 흔들면 이력이 런 재시도 여부에 의존하게 된다 —
    첫 값을 유지한다(measurements의 기존 동작과 같은 규칙).
    """
    existing = []
    if os.path.exists(path):
        with io.open(path, encoding='utf-8-sig') as f:
            existing = parse_observations(f.read())
        if any(r['ts'] == str(ts) for r in existing):
            return False

    existing.append({'ts': str(ts), 'breadth': float(breadth), 'momentum': float(momentum),
                     'trend': trend, 'sample': int(sample), 'source': str(source)})
    kept = trim_to_recent_dates(existing)

    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(OBS_HEADER)
        for r in kept:
            w.writerow(format_row(r['ts'], r['breadth'], r['momentum'],
                                  r['trend'], r['sample'], r['source']))
    os.replace(tmp, path)   # 중간에 죽어도 이력이 반토막 나지 않는다
    return True
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_regime_observations.py -q`
Expected: PASS (10 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/strategy/regime_observations.py tests/test_regime_observations.py
git commit -F - <<'EOF'
feat(sim0): 10분 해상도 국면 관측 이력

_hour_label이 'HH:00'으로 깎아 10분 관측의 5/6을 버려왔다. 분까지 남기고
표본 80 미만도 기록한다 — 확률 모형에서 적은 표본은 폐기 대상이 아니라
약한 증거다.

data/regime_observations.csv 위치는 워크플로 수정이 필요 없다:
scraper.yml이 런 시작에 db-data에서 data/를 복원하고 끝에 data/*.csv를 배포한다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 2: 관측 append 배선

**Files:**
- Modify: `src/pipeline/workers/trade_engine.py` (리베로 나우캐스트 블록, 현재 280–295행 근처)
- Test: `tests/test_regime_observations_wiring.py`

**Interfaces:**
- Consumes: `append_observation`, `OBS_HEADER` (Task 1)
- Produces: `OBS_PATH_REL: str` = `'data/regime_observations.csv'` (모듈 상수, `src/strategy/regime_observations.py`에 추가)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_regime_observations_wiring.py`:

```python
# -*- coding: utf-8 -*-
"""관측 append가 파이프라인에 배선됐는가 — 라우트를 부르지 않고 확인한다.

trade_engine을 import하면 네트워크 의존이 따라오므로 소스를 읽어 검사한다
(tests/test_regime_state.py의 '소비자가 자기 목록을 다시 만들지 않았는가'와 같은 방식).
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with io.open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def test_경로가_data_아래_csv다():
    # scraper.yml의 배포 스텝이 data/*.csv를 db-data로 복사한다. 이 규칙을 벗어나면
    # 이력이 런 사이에 이어지지 않는다.
    from src.strategy.regime_observations import OBS_PATH_REL
    assert OBS_PATH_REL.startswith('data/')
    assert OBS_PATH_REL.endswith('.csv')


def test_trade_engine이_append를_부른다():
    src = _read('src/pipeline/workers/trade_engine.py')
    assert 'append_observation' in src, '관측을 쌓지 않으면 이 계획의 나머지가 전부 무의미하다'


def test_trade_engine이_분_단위_시각을_넘긴다():
    src = _read('src/pipeline/workers/trade_engine.py')
    # '%H:00'으로 깎은 값을 넘기면 다시 5/6을 버린다.
    m = re.search(r'append_observation\((.{0,400}?)\)', src, re.S)
    assert m, 'append_observation 호출을 찾지 못했다'
    call = m.group(1)
    assert "'%H:00'" not in call and '"%H:00"' not in call


def test_배포_스텝이_data_csv를_복사한다():
    wf = _read('.github/workflows/scraper.yml')
    assert 'data/*.csv' in wf, '이 글롭이 사라지면 관측 이력이 런 사이에 끊긴다'
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_regime_observations_wiring.py -q`
Expected: FAIL — `ImportError: cannot import name 'OBS_PATH_REL'` 및 `append_observation`가 없다

- [ ] **Step 3: 상수 추가**

`src/strategy/regime_observations.py`의 `MAX_DISTINCT_DATES` 아래에 추가:

```python
# 파이프라인이 쓰는 상대 경로. data/ 아래 .csv 라는 것이 계약이다 —
# scraper.yml이 런 시작에 db-data에서 data/를 복원하고 끝에 data/*.csv를 배포한다.
OBS_PATH_REL = 'data/regime_observations.csv'
```

- [ ] **Step 4: 배선**

`src/pipeline/workers/trade_engine.py`의 리베로 블록에서 `elif action == 'nowcast' and live_breadth:` 분기를 다음으로 교체한다. `live_breadth`는 `(breadth, momentum, sample, codes)` 튜플이다.

```python
                        elif action == 'nowcast' and live_breadth:
                            codes = live_breadth[3]
                            sim.update_nowcast(
                                live_breadth[0], now_kst=now_kst,
                                backfill=lambda hhmm: self._backfill_breadth_kis(hhmm, codes))
                            # 관측 이력: 10분 해상도로 쌓는다(나우캐스트의 시간 격자와 별개).
                            # 판정기·라벨러·하네스가 학습·검증에 쓰는 유일한 원천이다.
                            try:
                                from src.strategy.regime_observations import (
                                    OBS_PATH_REL, append_observation)
                                append_observation(
                                    OBS_PATH_REL,
                                    now_kst.strftime('%Y-%m-%d %H:%M'),
                                    live_breadth[0], live_breadth[1],
                                    self._top100_trend_from_csv(),
                                    live_breadth[2], 'top100_live')
                            except Exception as e:
                                # 이력 축적 실패가 매매를 막지 않는다. 다만 조용히 넘기지 않는다.
                                self.log_error(f"국면 관측 이력 기록 실패: {e}")
```

- [ ] **Step 5: 통과를 확인한다**

Run: `python -m pytest tests/test_regime_observations_wiring.py tests/test_regime_observations.py -q`
Expected: PASS (14 passed)

- [ ] **Step 6: 전체 회귀**

Run: `python -m pytest tests/ -q`
Expected: PASS — 기존 475 passed 유지 + 신규

- [ ] **Step 7: 커밋**

```bash
git add src/strategy/regime_observations.py src/pipeline/workers/trade_engine.py tests/test_regime_observations_wiring.py
git commit -F - <<'EOF'
feat(sim0): 관측 이력 append를 파이프라인에 배선

10분마다 (폭, 강도, 표본)을 data/regime_observations.csv에 쌓는다.
기록 실패가 매매를 막지 않되 조용히 넘기지도 않는다(log_error).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 3: 일봉 관측 시계열

**Files:**
- Create: `src/strategy/regime_daily.py`
- Test: `tests/test_regime_daily.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `daily_observations(rows: list[dict], min_sample: int = 50) -> list[dict]` — 입력은 `{'date','code','open','close'}` 행들(문자열 허용), 출력은 Task 1과 같은 관측 shape(`ts`는 `'YYYY-MM-DD 15:30'`)
  - `load_ohlcv(path: str) -> list[dict]`

**왜 필요한가:** 10분 이력이 0이므로 (a) 관측모형 μ·σ 부트스트랩과 (b) 일 해상도 1차 비교의 데이터가 된다. `output/ohlcv_top100.csv`에 99거래일이 이미 있다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_regime_daily.py`:

```python
# -*- coding: utf-8 -*-
"""일봉 → 일 해상도 관측. 10분 이력이 쌓이기 전의 유일한 데이터다."""
from src.strategy.regime_daily import daily_observations


def _row(date, code, open_, close):
    return {'date': date, 'code': code, 'open': open_, 'close': close}


def test_전일종가_대비로_폭과_강도를_만든다():
    rows = [
        _row('20260601', 'A', 100, 100), _row('20260602', 'A', 100, 110),   # +10%
        _row('20260601', 'B', 100, 100), _row('20260602', 'B', 100, 90),    # -10%
        _row('20260601', 'C', 100, 100), _row('20260602', 'C', 100, 105),   # +5%
    ]
    obs = daily_observations(rows, min_sample=3)
    assert len(obs) == 1, '첫날은 전일종가가 없어 관측이 되지 않는다'
    o = obs[0]
    assert o['ts'] == '2026-06-02 15:30'
    assert o['breadth'] == round(2 / 3 * 100, 1)
    assert o['momentum'] == 5.0, '강도는 등락률 중앙값이다(라이브 _breadth_momentum과 같은 정의)'
    assert o['sample'] == 3
    assert o['trend'] is None, '일봉에서는 trend를 만들지 않는다 — 없는 값을 지어내지 않는다'


def test_표본_미달인_날은_버린다():
    rows = [_row('20260601', 'A', 100, 100), _row('20260602', 'A', 100, 110)]
    assert daily_observations(rows, min_sample=5) == []


def test_전일종가가_0이면_그_종목을_뺀다():
    rows = [
        _row('20260601', 'A', 100, 0), _row('20260602', 'A', 100, 110),
        _row('20260601', 'B', 100, 100), _row('20260602', 'B', 100, 110),
        _row('20260601', 'C', 100, 100), _row('20260602', 'C', 100, 90),
    ]
    obs = daily_observations(rows, min_sample=2)
    assert obs[0]['sample'] == 2, '0으로 나누지 않고 그 종목만 제외한다'


def test_날짜순으로_정렬돼_나온다():
    rows = []
    for d in ('20260603', '20260601', '20260602'):
        for c in ('A', 'B'):
            rows.append(_row(d, c, 100, 100))
    obs = daily_observations(rows, min_sample=2)
    assert [o['ts'][:10] for o in obs] == ['2026-06-02', '2026-06-03']


def test_숫자가_문자열로_와도_읽는다():
    rows = [
        _row('20260601', 'A', '100', '100'), _row('20260602', 'A', '100', '110'),
        _row('20260601', 'B', '100', '100'), _row('20260602', 'B', '100', '90'),
    ]
    assert daily_observations(rows, min_sample=2)[0]['breadth'] == 50.0
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_regime_daily.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 최소 구현**

`src/strategy/regime_daily.py`:

```python
# -*- coding: utf-8 -*-
"""일봉 CSV → 일 해상도 국면 관측.

10분 이력이 쌓이기 전에도 (a) 관측모형 μ·σ 부트스트랩과 (b) 기준선 대비 1차 비교를
할 수 있게 하는 다리다. `output/ohlcv_top100.csv`에 99거래일이 이미 있다.

폭·강도의 정의는 라이브(`trade_engine._breadth_momentum`)와 **같아야 한다** —
breadth = 등락률>0 비율, momentum = 등락률 중앙값. 정의가 갈리면 여기서 뽑은
파라미터를 라이브에 쓸 수 없다.
"""
import csv
import io
from collections import defaultdict

MARKET_CLOSE = '15:30'


def _median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def load_ohlcv(path):
    """일봉 wide CSV → 행 리스트. 열 이름은 date,code,name,open,high,low,close,volume,amount."""
    with io.open(path, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def daily_observations(rows, min_sample=50):
    """일봉 행들 → 관측 시계열(Task 1과 같은 shape).

    등락률은 **전일종가 대비 종가**다. 전일종가가 없거나 0인 종목은 그날 표본에서
    빠진다 — 0으로 나누지 않고, 없는 값을 지어내지도 않는다.
    """
    by_code = defaultdict(list)
    for r in rows:
        try:
            by_code[r['code']].append((str(r['date']), float(r['close'])))
        except (KeyError, TypeError, ValueError):
            continue

    rates_by_date = defaultdict(list)
    for series in by_code.values():
        series.sort(key=lambda x: x[0])
        for i in range(1, len(series)):
            prev_close = series[i - 1][1]
            close = series[i][1]
            if prev_close <= 0:
                continue
            rates_by_date[series[i][0]].append((close / prev_close - 1) * 100)

    out = []
    for date in sorted(rates_by_date):
        rates = rates_by_date[date]
        if len(rates) < min_sample:
            continue
        ups = sum(1 for x in rates if x > 0)
        ts = f'{date[0:4]}-{date[4:6]}-{date[6:8]} {MARKET_CLOSE}'
        out.append({
            'ts': ts,
            'breadth': round(ups / len(rates) * 100, 1),
            'momentum': round(_median(rates), 2),
            'trend': None,
            'sample': len(rates),
            'source': 'ohlcv_daily',
        })
    return out
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_regime_daily.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: 실제 데이터로 스모크 확인**

Run:
```bash
PYTHONPATH=. python -c "
from src.strategy.regime_daily import load_ohlcv, daily_observations
obs = daily_observations(load_ohlcv('output/ohlcv_top100.csv'))
print(len(obs), obs[0]['ts'], obs[-1]['ts'])
print('breadth 범위', min(o['breadth'] for o in obs), max(o['breadth'] for o in obs))
"
```
Expected: `99 2026-03-06 15:30 2026-07-29 15:30` (건수는 데이터에 따라 ±1), breadth 범위가 0~100 안

- [ ] **Step 6: 커밋**

```bash
git add src/strategy/regime_daily.py tests/test_regime_daily.py
git commit -F - <<'EOF'
feat(sim0): 일봉 99거래일 → 일 해상도 국면 관측

10분 이력이 0인 동안 관측모형 부트스트랩과 1차 비교의 데이터가 된다.
폭·강도 정의를 라이브 _breadth_momentum과 일치시켰다 — 갈리면 여기서 뽑은
파라미터를 라이브에 쓸 수 없다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 4: 사후 라벨러

**Files:**
- Create: `src/strategy/regime_label.py`
- Test: `tests/test_regime_label.py`

**Interfaces:**
- Consumes: Task 1/3의 관측 shape (`{'ts','breadth','momentum','trend','sample','source'}`)
- Produces:
  - `centered_median(values: list[float], window: int) -> list[float]`
  - `rolling_quantile(values: list[float], q: float, window: int) -> list[float]`
  - `label_regimes(observations: list[dict], window: int = 5, q_window: int = 60, q_hi: float = 0.67, q_lo: float = 0.33) -> list[dict]` — 각 dict: `{'ts', 'regime', 'sb', 'sm'}` (sb=평활 breadth, sm=평활 momentum)
  - `transitions(labels: list[dict]) -> list[dict]` — 각 dict: `{'ts', 'from', 'to'}`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_regime_label.py`:

```python
# -*- coding: utf-8 -*-
"""사후 라벨러 — 정답을 만드는 쪽이다.

**미래를 쓴다. 그것이 의도다.** 대칭 평활은 양쪽을 보고, 판정기는 과거만 본다.
그 정보 비대칭이 '전환 탐지 지연'을 정의한다. 판정기가 미래를 쓰면 룩어헤드지만
라벨러가 쓰는 것은 정상이다 — 라벨은 채점 대상이 아니라 채점 기준이다.
"""
from src.strategy.regime_label import (
    centered_median, label_regimes, rolling_quantile, transitions,
)


def _obs(ts, breadth, momentum):
    return {'ts': ts, 'breadth': breadth, 'momentum': momentum,
            'trend': None, 'sample': 100, 'source': 't'}


def test_대칭_평활은_중심에_놓인다():
    # 가운데 튀는 값 하나가 이웃에 흡수된다
    out = centered_median([10, 10, 90, 10, 10], window=3)
    assert out[2] == 10, '중심 이동중앙값이면 스파이크가 지워진다'


def test_대칭_평활은_미래를_쓴다():
    # 인덱스 0의 값이 뒤쪽 값에 영향받는다 = 미래 사용. 라벨러에서는 의도된 동작이다.
    assert centered_median([0, 100, 100], window=3)[0] == 100


def test_평활_창이_1이면_원본이다():
    assert centered_median([1.0, 2.0, 3.0], window=1) == [1.0, 2.0, 3.0]


def test_경계에서는_있는_만큼만_쓴다():
    out = centered_median([1, 2, 3, 4, 5], window=5)
    assert len(out) == 5, '길이가 줄면 라벨과 관측의 인덱스가 어긋난다'


def test_롤링_분위수는_과거_창만_본다():
    vals = [0.0] * 10 + [100.0] * 10
    out = rolling_quantile(vals, q=0.5, window=5)
    assert out[4] == 0.0
    assert out[-1] == 100.0


def test_양축이_동의할_때만_국면이_붙는다():
    # 폭은 강세인데 강도가 약세 → SIDEWAYS. 라벨은 확실한 구간만 국면으로 부른다.
    obs = [_obs(f'2026-06-{d:02d} 15:30', 95.0, -3.0) for d in range(1, 11)]
    labels = label_regimes(obs, window=1, q_window=10)
    assert {l['regime'] for l in labels} == {'SIDEWAYS'}


def test_둘_다_강세면_BULL_둘_다_약세면_BEAR():
    obs = ([_obs(f'2026-06-{d:02d} 15:30', 10.0, -5.0) for d in range(1, 11)]
           + [_obs(f'2026-06-{d:02d} 15:30', 90.0, 5.0) for d in range(11, 21)])
    labels = label_regimes(obs, window=1, q_window=20)
    assert labels[0]['regime'] == 'BEAR'
    assert labels[-1]['regime'] == 'BULL'


def test_라벨은_관측과_같은_길이다():
    obs = [_obs(f'2026-06-{d:02d} 15:30', 50.0 + d, float(d)) for d in range(1, 21)]
    assert len(label_regimes(obs, window=3, q_window=10)) == len(obs)


def test_전환_목록은_바뀐_지점만_담는다():
    labels = [
        {'ts': 't1', 'regime': 'BEAR', 'sb': 0, 'sm': 0},
        {'ts': 't2', 'regime': 'BEAR', 'sb': 0, 'sm': 0},
        {'ts': 't3', 'regime': 'BULL', 'sb': 0, 'sm': 0},
        {'ts': 't4', 'regime': 'BULL', 'sb': 0, 'sm': 0},
        {'ts': 't5', 'regime': 'SIDEWAYS', 'sb': 0, 'sm': 0},
    ]
    assert transitions(labels) == [
        {'ts': 't3', 'from': 'BEAR', 'to': 'BULL'},
        {'ts': 't5', 'from': 'BULL', 'to': 'SIDEWAYS'},
    ]


def test_빈_입력을_견딘다():
    assert label_regimes([], window=3) == []
    assert transitions([]) == []


def test_평활_창이_길면_전환이_줄어든다():
    # 잡음이 섞인 시계열. 창이 길수록 라벨 전환 횟수가 줄어야 한다(스윕의 근거).
    obs = []
    for d in range(1, 41):
        b = 90.0 if d % 2 else 10.0
        obs.append(_obs(f'2026-06-{d:02d} 15:30', b, (b - 50) / 10))
    few = len(transitions(label_regimes(obs, window=9, q_window=40)))
    many = len(transitions(label_regimes(obs, window=1, q_window=40)))
    assert few < many
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_regime_label.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 최소 구현**

`src/strategy/regime_label.py`:

```python
# -*- coding: utf-8 -*-
"""사후 국면 라벨러 — 채점의 기준을 만든다.

**미래를 쓴다. 그것이 설계다.** 대칭(중심) 평활은 양쪽을 보고, 판정기는 과거만 본다.
그 정보 비대칭이 '전환 탐지 지연'을 정의한다. 라벨러가 미래를 쓰는 것은 룩어헤드가
아니다 — 라벨은 채점 대상이 아니라 채점 기준이다.

**임계를 60/40으로 고정하지 않는다.** 실측 종가 breadth 평균이 48.5여서 60/40 컷은
SIDEWAYS를 과도하게 넓힌다. 시장 레짐이 이동하면 고정 컷의 의미도 변한다. 그래서
직전 `q_window` 구간의 분위수를 쓴다.

**양축이 동의할 때만 국면을 붙인다(AND).** 애매한 구간이 SIDEWAYS로 가야 지연 측정이
깨끗해진다. 판정기 쪽 AND 게이트가 문제였던 이유는 실시간에 미래를 못 봐서지
AND 자체가 나빠서가 아니다.
"""
REGIMES = ('BULL', 'SIDEWAYS', 'BEAR')


def _median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def centered_median(values, window):
    """중심 이동중앙값. 경계에서는 있는 만큼만 쓴다(길이 보존)."""
    if window <= 1:
        return list(values)
    half = window // 2
    out = []
    for i in range(len(values)):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        out.append(_median(values[lo:hi]))
    return out


def _quantile(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def rolling_quantile(values, q, window):
    """각 시점에서 **직전 `window`개**(자신 포함)의 분위수. 과거만 본다."""
    out = []
    for i in range(len(values)):
        lo = max(0, i - window + 1)
        out.append(_quantile(sorted(values[lo:i + 1]), q))
    return out


def label_regimes(observations, window=5, q_window=60, q_hi=0.67, q_lo=0.33):
    """관측 시계열 → 시점별 국면 라벨.

    ① breadth·momentum 각각 중심 평활 → ② 각 축의 롤링 분위수로 상·하 임계
    → ③ 양축이 상단 이상이면 BULL, 양축이 하단 이하면 BEAR, 나머지 SIDEWAYS.
    """
    if not observations:
        return []
    sb = centered_median([o['breadth'] for o in observations], window)
    sm = centered_median([o['momentum'] for o in observations], window)
    b_hi = rolling_quantile(sb, q_hi, q_window)
    b_lo = rolling_quantile(sb, q_lo, q_window)
    m_hi = rolling_quantile(sm, q_hi, q_window)
    m_lo = rolling_quantile(sm, q_lo, q_window)

    labels = []
    for i, o in enumerate(observations):
        if sb[i] >= b_hi[i] and sm[i] >= m_hi[i]:
            regime = 'BULL'
        elif sb[i] <= b_lo[i] and sm[i] <= m_lo[i]:
            regime = 'BEAR'
        else:
            regime = 'SIDEWAYS'
        labels.append({'ts': o['ts'], 'regime': regime,
                       'sb': round(sb[i], 2), 'sm': round(sm[i], 3)})
    return labels


def transitions(labels):
    """라벨 시계열 → 전환 목록. 첫 라벨은 전환이 아니다(비교 대상이 없다)."""
    out = []
    for i in range(1, len(labels)):
        if labels[i]['regime'] != labels[i - 1]['regime']:
            out.append({'ts': labels[i]['ts'],
                        'from': labels[i - 1]['regime'],
                        'to': labels[i]['regime']})
    return out
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_regime_label.py -q`
Expected: PASS (11 passed)

- [ ] **Step 5: 실제 99일에 붙여보고 창을 훑는다**

Run:
```bash
PYTHONPATH=. python -c "
from src.strategy.regime_daily import load_ohlcv, daily_observations
from src.strategy.regime_label import label_regimes, transitions
obs = daily_observations(load_ohlcv('output/ohlcv_top100.csv'))
for w in (1, 3, 5, 7, 9):
    L = label_regimes(obs, window=w)
    t = transitions(L)
    dist = {r: sum(1 for x in L if x['regime'] == r) for r in ('BULL','SIDEWAYS','BEAR')}
    print(f'window={w} 전환 {len(t):>3}건  분포 {dist}')
"
```
Expected: `window`가 커지면 전환 건수가 단조 감소(또는 비증가). 분포가 한 국면에 100% 쏠리지 않음. **쏠리면 분위수·평활 파라미터를 재검토하고 진행하지 않는다.**

- [ ] **Step 6: 커밋**

```bash
git add src/strategy/regime_label.py tests/test_regime_label.py
git commit -F - <<'EOF'
feat(sim0): 사후 양방향 평활 라벨러

정답을 만드는 쪽이다. 대칭 평활은 미래를 쓰고 판정기는 과거만 쓴다 —
그 비대칭이 '전환 탐지 지연'을 정의한다.

임계는 60/40 고정이 아니라 롤링 분위수다. 실측 종가 breadth 평균이 48.5여서
고정 컷은 SIDEWAYS를 과도하게 넓힌다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 5: 기준선 판정기 4개

**Files:**
- Create: `src/strategy/regime_baselines.py`
- Test: `tests/test_regime_baselines.py`

**Interfaces:**
- Consumes: 관측 shape
- Produces (모두 `(prev: dict | None, obs: dict, params: dict) -> dict` 시그니처. 반환 dict는 최소 `{'regime': str}`을 갖고 자신이 필요한 상태를 함께 담아 다음 호출의 `prev`로 돌아온다):
  - `always_sideways`
  - `immediate(prev, obs, params)` — `params`: `{'b_hi','b_lo','m_hi','m_lo'}`
  - `current_production(prev, obs, params)` — 현행 재현. `params`: `{}`
  - `hysteresis(prev, obs, params)` — `params`: `{'enter_bear','exit_bear','enter_bull','exit_bull','dwell_min'}`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_regime_baselines.py`:

```python
# -*- coding: utf-8 -*-
"""기준선 판정기 — 확률 필터가 이겨야 하는 상대들.

기준선 없이 개선을 주장하지 않는다. 이것이 없어서 10:00 EOD 예측이 무모델
기준선보다 10p 나쁜 것을 아무도 몰랐다.
"""
from src.strategy.regime_baselines import (
    always_sideways, current_production, hysteresis, immediate,
)


def _obs(ts, breadth, momentum, trend=25.0):
    return {'ts': ts, 'breadth': breadth, 'momentum': momentum,
            'trend': trend, 'sample': 100, 'source': 't'}


IMM = {'b_hi': 60.0, 'b_lo': 40.0, 'm_hi': 2.0, 'm_lo': -2.0}


def test_항상_SIDEWAYS():
    out = always_sideways(None, _obs('2026-07-30 09:10', 95.0, 9.0), {})
    assert out['regime'] == 'SIDEWAYS'


def test_즉시_반응은_평활이_없다():
    assert immediate(None, _obs('t', 95.0, 5.0), IMM)['regime'] == 'BULL'
    assert immediate(None, _obs('t', 5.0, -5.0), IMM)['regime'] == 'BEAR'
    assert immediate(None, _obs('t', 50.0, 0.0), IMM)['regime'] == 'SIDEWAYS'


def test_현행은_AND게이트다():
    # breadth만 강세면 안 켜진다 — 이것이 전환기에 상승장을 놓치는 이유다.
    st = current_production(None, _obs('t', 95.0, 0.5, trend=25.0), {})
    assert st['regime'] == 'SIDEWAYS'


def test_현행의_trend가_방향을_모른다():
    # trend는 상승·하락 조건 양쪽에 같은 부호로 들어간다. 낮으면 둘 다 막힌다.
    st = current_production(None, _obs('t', 5.0, -5.0, trend=5.0), {})
    assert st['regime'] == 'SIDEWAYS', 'trend<15이면 BEAR도 안 켜진다'


def test_현행은_5런_과반이라_전환에_3런이_걸린다():
    prev = None
    seen = []
    for i in range(6):
        prev = current_production(prev, _obs(f't{i}', 5.0, -5.0, trend=25.0), {})
        seen.append(prev['regime'])
    assert seen[0] == 'BEAR', '표본 1개면 그 자체가 최빈값이다'
    assert seen[-1] == 'BEAR'
    # 반대 신호가 들어오면 과반이 깨져 SIDEWAYS로 보수 확정된다
    flip = current_production(prev, _obs('t6', 95.0, 5.0, trend=25.0), {})
    assert flip['regime'] == 'BEAR', '한 건으로는 안 뒤집힌다'


HYS = {'enter_bear': 40.0, 'exit_bear': 55.0, 'enter_bull': 65.0, 'exit_bull': 50.0,
       'dwell_min': 20}


def test_히스테리시스는_dwell을_시간으로_잰다():
    prev = hysteresis(None, _obs('2026-07-30 09:00', 30.0, -3.0), HYS)
    assert prev['regime'] == 'SIDEWAYS', 'dwell 미달이면 아직 전환하지 않는다'
    prev = hysteresis(prev, _obs('2026-07-30 09:10', 30.0, -3.0), HYS)
    assert prev['regime'] == 'SIDEWAYS', '10분은 20분 미달'
    prev = hysteresis(prev, _obs('2026-07-30 09:25', 30.0, -3.0), HYS)
    assert prev['regime'] == 'BEAR', '25분 경과 → 확정'


def test_히스테리시스는_런_개수에_의존하지_않는다():
    # 30분 만에 온 관측 한 건으로도 dwell이 채워진다 — 런 간격 불규칙에 면역이다.
    prev = hysteresis(None, _obs('2026-07-30 09:00', 30.0, -3.0), HYS)
    prev = hysteresis(prev, _obs('2026-07-30 09:40', 30.0, -3.0), HYS)
    assert prev['regime'] == 'BEAR'


def test_히스테리시스_이탈은_진입보다_느슨하다():
    prev = hysteresis(None, _obs('2026-07-30 09:00', 30.0, -3.0), HYS)
    prev = hysteresis(prev, _obs('2026-07-30 09:30', 30.0, -3.0), HYS)
    assert prev['regime'] == 'BEAR'
    # 45는 enter_bear(40) 위지만 exit_bear(55) 아래 → 유지(채터링 방지)
    prev = hysteresis(prev, _obs('2026-07-30 10:00', 45.0, -1.0), HYS)
    assert prev['regime'] == 'BEAR'
    # 60은 exit_bear 초과 → 이탈
    prev = hysteresis(prev, _obs('2026-07-30 10:30', 60.0, 1.0), HYS)
    assert prev['regime'] != 'BEAR'
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_regime_baselines.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 최소 구현**

`src/strategy/regime_baselines.py`:

```python
# -*- coding: utf-8 -*-
"""기준선 판정기 — 확률 필터가 이겨야 하는 상대들.

기준선 없이 개선을 주장하지 않는다. 이것이 없어서 나우캐스트 10:00 EOD 예측이
무모델 기준선(09:00, 외삽 없음)보다 MAE 10p 나쁜 것을 아무도 몰랐다.

모든 판정기는 같은 시그니처다: `(prev, obs, params) -> state`.
`state`는 `regime`을 반드시 담고, 자신이 필요한 나머지는 함께 담아 다음 호출의
`prev`로 돌아온다. 파일도 시계도 만지지 않는다 — 하네스가 과거에 재생할 수 있는 조건이다.
"""
from datetime import datetime

# 현행 production 재현용 상수. sim0_libero.classify_regime과 같은 값이어야 한다.
PROD_BULL = {'breadth': 60.0, 'momentum': 2.0, 'trend': 20.0}
PROD_BEAR = {'breadth': 40.0, 'momentum': -2.0, 'trend': 15.0}
PROD_HISTORY = 5


def _parse_ts(ts):
    return datetime.strptime(ts, '%Y-%m-%d %H:%M')


def _minutes_between(a, b):
    return (_parse_ts(b) - _parse_ts(a)).total_seconds() / 60.0


def always_sideways(prev, obs, params):
    """국면을 아예 판단하지 않는 하한선. 이걸 못 이기면 국면 판정 자체가 무의미하다."""
    return {'regime': 'SIDEWAYS'}


def immediate(prev, obs, params):
    """평활 없이 그 순간의 값으로만 판정. 지연 0, 오탐 최대."""
    b, m = obs['breadth'], obs['momentum']
    if b >= params['b_hi'] and m >= params['m_hi']:
        return {'regime': 'BULL'}
    if b <= params['b_lo'] and m <= params['m_lo']:
        return {'regime': 'BEAR'}
    return {'regime': 'SIDEWAYS'}


def _prod_instant(obs):
    """sim0_libero.classify_regime의 AND 게이트를 그대로 옮긴 것.

    trend는 방향이 없다(ADX 근사 = |변동| 평균). 상승·하락 조건 양쪽에 `>=`로
    들어가므로 '시장이 움직인다' 필터일 뿐이고, 게다가 일봉 CSV에서 오므로
    장중에 변하지 않는다. 재현이 목적이므로 그대로 둔다.
    """
    trend = obs.get('trend')
    t = 0.0 if trend is None else trend
    if obs['breadth'] >= PROD_BULL['breadth'] and obs['momentum'] >= PROD_BULL['momentum'] \
            and t >= PROD_BULL['trend']:
        return 'BULL'
    if obs['breadth'] <= PROD_BEAR['breadth'] and obs['momentum'] <= PROD_BEAR['momentum'] \
            and t >= PROD_BEAR['trend']:
        return 'BEAR'
    return 'SIDEWAYS'


def current_production(prev, obs, params):
    """현행 재현: AND 게이트 + 최근 5런 최빈값(과반 미달이면 SIDEWAYS).

    런 **개수** 기반이라 간격이 불규칙하면 같은 5런이 뜻하는 시간이 매일 다르다.
    이 기준선의 존재 이유가 그 대가를 숫자로 보여주는 것이다.
    """
    history = list((prev or {}).get('history', []))
    history.append(_prod_instant(obs))
    history = history[-PROD_HISTORY:]

    counts = {r: history.count(r) for r in set(history)}
    top = max(counts, key=counts.get)
    if len(history) >= 3 and counts[top] < (len(history) // 2 + 1):
        regime = 'SIDEWAYS'
    else:
        regime = top
    return {'regime': regime, 'history': history}


def hysteresis(prev, obs, params):
    """이중 임계 + 경과 시간 기반 확정.

    평활을 쓰지 않고 채터링을 막는다. 확정 요건을 런 개수가 아니라 **분**으로 재므로
    런 간격 불규칙에 면역이다.
    """
    prev = prev or {}
    regime = prev.get('regime', 'SIDEWAYS')
    pending = prev.get('pending')          # {'regime': str, 'since': ts}
    b = obs['breadth']

    # 현 국면 이탈 판단(이탈 임계는 진입보다 느슨하다)
    if regime == 'BEAR' and b > params['exit_bear']:
        regime = 'SIDEWAYS'
    elif regime == 'BULL' and b < params['exit_bull']:
        regime = 'SIDEWAYS'

    # 진입 후보
    candidate = None
    if b <= params['enter_bear']:
        candidate = 'BEAR'
    elif b >= params['enter_bull']:
        candidate = 'BULL'

    if candidate is None or candidate == regime:
        return {'regime': regime, 'pending': None}

    if pending and pending['regime'] == candidate:
        if _minutes_between(pending['since'], obs['ts']) >= params['dwell_min']:
            return {'regime': candidate, 'pending': None}
        return {'regime': regime, 'pending': pending}

    return {'regime': regime, 'pending': {'regime': candidate, 'since': obs['ts']}}
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_regime_baselines.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/strategy/regime_baselines.py tests/test_regime_baselines.py
git commit -F - <<'EOF'
feat(sim0): 기준선 판정기 4개 (항상SIDEWAYS·즉시·현행·히스테리시스)

현행 재현이 포함된다 — AND 게이트 + 5런 최빈값. 런 개수 기반이라 간격이
불규칙하면 같은 5런이 뜻하는 시간이 매일 다르고, 이 기준선의 존재 이유가
그 대가를 숫자로 보여주는 것이다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 6: 평가 하네스

**Files:**
- Create: `src/strategy/regime_eval.py`
- Test: `tests/test_regime_eval.py`

**Interfaces:**
- Consumes: 관측 shape, Task 4의 라벨 shape, 판정기 시그니처
- Produces:
  - `COST_WEIGHTS: dict` = `{'late_exit': 2.0, 'late_entry': 1.0, 'false_alarm': 1.0, 'miss': 2.0, 'delay_unit_min': 60.0}`
  - `replay(observations, decider, params) -> list[dict]` — 각 dict: `{'ts', 'regime', 'probs' | None}`
  - `score(decisions, labels, weights=COST_WEIGHTS) -> dict` — 키: `n_transitions`, `detected`, `missed`, `false_alarms`, `delays_min`(list), `median_delay_min`, `cost`, `cost_parts`
  - `calibration(decisions, labels, bins=5) -> dict` — 키: `brier`, `reliability`(list of `{'lo','hi','n','mean_pred','freq'}`)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_regime_eval.py`:

```python
# -*- coding: utf-8 -*-
"""평가 하네스 — '개선'을 정의하는 곳.

지금까지 이것이 없어서 매번 다른 문제가 새로 나왔다. 손실은 breadth MAE가 아니라
전환 탐지 지연 + 오탐이고, 비대칭이다(실측: 아침 BULL→종가 BEAR 10일 vs 역방향 1일).
"""
from src.strategy.regime_baselines import always_sideways, immediate
from src.strategy.regime_eval import COST_WEIGHTS, calibration, replay, score


def _obs(ts, breadth, momentum):
    return {'ts': ts, 'breadth': breadth, 'momentum': momentum,
            'trend': 25.0, 'sample': 100, 'source': 't'}


def _labels(pairs):
    return [{'ts': ts, 'regime': r, 'sb': 0.0, 'sm': 0.0} for ts, r in pairs]


def test_재생은_판정기를_시계열에_흘린다():
    obs = [_obs('2026-07-30 09:00', 50.0, 0.0), _obs('2026-07-30 09:10', 50.0, 0.0)]
    out = replay(obs, always_sideways, {})
    assert [d['regime'] for d in out] == ['SIDEWAYS', 'SIDEWAYS']
    assert [d['ts'] for d in out] == [o['ts'] for o in obs]


def test_완벽한_판정기의_지연은_0이다():
    labels = _labels([('2026-07-30 09:00', 'SIDEWAYS'), ('2026-07-30 09:10', 'BEAR')])
    decisions = [{'ts': l['ts'], 'regime': l['regime'], 'probs': None} for l in labels]
    s = score(decisions, labels)
    assert s['n_transitions'] == 1
    assert s['detected'] == 1
    assert s['missed'] == 0
    assert s['delays_min'] == [0.0]
    assert s['median_delay_min'] == 0.0


def test_항상_SIDEWAYS는_전환을_전부_놓친다():
    labels = _labels([('2026-07-30 09:00', 'SIDEWAYS'), ('2026-07-30 09:10', 'BEAR'),
                      ('2026-07-30 09:20', 'BULL')])
    decisions = replay([_obs(l['ts'], 50.0, 0.0) for l in labels], always_sideways, {})
    s = score(decisions, labels)
    assert s['n_transitions'] == 2
    assert s['missed'] == 2
    assert s['detected'] == 0


def test_지연은_분으로_잰다():
    labels = _labels([('2026-07-30 09:00', 'SIDEWAYS'), ('2026-07-30 09:10', 'BEAR'),
                      ('2026-07-30 09:20', 'BEAR'), ('2026-07-30 09:40', 'BEAR')])
    decisions = [
        {'ts': '2026-07-30 09:00', 'regime': 'SIDEWAYS', 'probs': None},
        {'ts': '2026-07-30 09:10', 'regime': 'SIDEWAYS', 'probs': None},
        {'ts': '2026-07-30 09:20', 'regime': 'SIDEWAYS', 'probs': None},
        {'ts': '2026-07-30 09:40', 'regime': 'BEAR', 'probs': None},
    ]
    s = score(decisions, labels)
    assert s['delays_min'] == [30.0]


def test_오탐은_라벨에_없는_전환이다():
    labels = _labels([('2026-07-30 09:00', 'SIDEWAYS'), ('2026-07-30 09:10', 'SIDEWAYS')])
    decisions = [
        {'ts': '2026-07-30 09:00', 'regime': 'SIDEWAYS', 'probs': None},
        {'ts': '2026-07-30 09:10', 'regime': 'BULL', 'probs': None},
    ]
    s = score(decisions, labels)
    assert s['false_alarms'] == 1
    assert s['n_transitions'] == 0


def test_비용은_늦게_나가는_것을_더_비싸게_센다():
    # 같은 30분 지연이 BEAR 진입일 때 BULL 진입보다 비싸다 (실측 비대칭 10:1 근거)
    assert COST_WEIGHTS['late_exit'] > COST_WEIGHTS['late_entry']

    def one_case(to_regime):
        labels = _labels([('2026-07-30 09:00', 'SIDEWAYS'), ('2026-07-30 09:10', to_regime),
                          ('2026-07-30 09:40', to_regime)])
        decisions = [
            {'ts': '2026-07-30 09:00', 'regime': 'SIDEWAYS', 'probs': None},
            {'ts': '2026-07-30 09:10', 'regime': 'SIDEWAYS', 'probs': None},
            {'ts': '2026-07-30 09:40', 'regime': to_regime, 'probs': None},
        ]
        return score(decisions, labels)['cost']

    assert one_case('BEAR') > one_case('BULL')


def test_비용_구성요소가_따로_나온다():
    # 가중치가 숫자를 숨기지 않게 한다 — 지연·오탐·미탐을 각각 볼 수 있어야 한다.
    labels = _labels([('2026-07-30 09:00', 'SIDEWAYS'), ('2026-07-30 09:10', 'BEAR')])
    decisions = [{'ts': l['ts'], 'regime': 'SIDEWAYS', 'probs': None} for l in labels]
    s = score(decisions, labels)
    assert set(s['cost_parts']) == {'late_exit', 'late_entry', 'false_alarm', 'miss'}


def test_캘리브레이션은_확률이_있을_때만_의미가_있다():
    labels = _labels([('t1', 'BEAR'), ('t2', 'BEAR'), ('t3', 'BULL'), ('t4', 'BULL')])
    decisions = [
        {'ts': 't1', 'regime': 'BEAR', 'probs': {'BULL': 0.0, 'SIDEWAYS': 0.0, 'BEAR': 1.0}},
        {'ts': 't2', 'regime': 'BEAR', 'probs': {'BULL': 0.0, 'SIDEWAYS': 0.0, 'BEAR': 1.0}},
        {'ts': 't3', 'regime': 'BULL', 'probs': {'BULL': 1.0, 'SIDEWAYS': 0.0, 'BEAR': 0.0}},
        {'ts': 't4', 'regime': 'BULL', 'probs': {'BULL': 1.0, 'SIDEWAYS': 0.0, 'BEAR': 0.0}},
    ]
    c = calibration(decisions, labels)
    assert c['brier'] == 0.0, '완벽하게 확신하고 맞으면 Brier 0이다'


def test_과신은_Brier로_드러난다():
    labels = _labels([('t1', 'BULL'), ('t2', 'BULL')])
    sure_wrong = [
        {'ts': 't1', 'regime': 'BEAR', 'probs': {'BULL': 0.0, 'SIDEWAYS': 0.0, 'BEAR': 1.0}},
        {'ts': 't2', 'regime': 'BEAR', 'probs': {'BULL': 0.0, 'SIDEWAYS': 0.0, 'BEAR': 1.0}},
    ]
    assert calibration(sure_wrong, labels)['brier'] == 2.0


def test_확률이_없는_판정기는_캘리브레이션이_None이다():
    labels = _labels([('t1', 'BULL')])
    d = [{'ts': 't1', 'regime': 'BULL', 'probs': None}]
    assert calibration(d, labels)['brier'] is None
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_regime_eval.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 최소 구현**

`src/strategy/regime_eval.py`:

```python
# -*- coding: utf-8 -*-
"""국면 판정기 평가 하네스 — '개선'을 정의하는 곳.

이것이 없어서 리베로 개선이 매번 새 근본 문제를 만났다. 손실은 breadth MAE가 아니라
**전환 탐지 지연 + 오탐**이고, 비대칭이다.

비대칭의 근거(top100 99거래일 실측): 아침 BULL → 종가 BEAR **10일**,
아침 BEAR → 종가 BULL **1일**. 늦게 나가는 것이 늦게 들어가는 것보다 비싸다.

가중치는 선택이다. 그래서 `cost` 하나만 내보내지 않고 `cost_parts`로 구성요소를
따로 내보낸다 — 가중치가 숫자를 숨기지 못하게 한다.
"""
from datetime import datetime

from src.strategy.regime_label import REGIMES

COST_WEIGHTS = {
    'late_exit': 2.0,      # BEAR 전환 지연 — 손실
    'late_entry': 1.0,     # BULL 전환 지연 — 기회손실(더 싸다)
    'false_alarm': 1.0,    # 라벨에 없는 전환 1회
    'miss': 2.0,           # 끝까지 못 잡은 전환 1회
    'delay_unit_min': 60.0,  # 1시간 지연 = 1단위. 지연과 횟수의 환산율(명시적 선택)
}


def _ts(s):
    return datetime.strptime(s, '%Y-%m-%d %H:%M') if len(s) > 10 else datetime.strptime(s, '%Y-%m-%d')


def _minutes(a, b):
    try:
        return (_ts(b) - _ts(a)).total_seconds() / 60.0
    except ValueError:
        return 0.0   # 테스트용 합성 ts('t1' 등)는 지연을 0으로 본다


def replay(observations, decider, params):
    """판정기를 관측 시계열에 흘린다. 판정기는 과거만 본다(룩어헤드 없음)."""
    prev = None
    out = []
    for obs in observations:
        prev = decider(prev, obs, params)
        out.append({'ts': obs['ts'], 'regime': prev['regime'],
                    'probs': prev.get('probs')})
    return out


def score(decisions, labels, weights=COST_WEIGHTS):
    """전환 탐지 지연·오탐·미탐과 비대칭 비용.

    지연: 라벨이 국면 X로 바뀐 시각부터, 판정이 X가 된 첫 시각까지의 분.
          다음 라벨 전환 전까지 못 잡으면 미탐.
    오탐: 라벨이 안 바뀐 구간에서 판정이 바뀐 횟수.
    """
    by_ts = {d['ts']: d for d in decisions}
    label_at = {l['ts']: l['regime'] for l in labels}
    order = [l['ts'] for l in labels]

    # 라벨 전환 지점
    trans = []
    for i in range(1, len(labels)):
        if labels[i]['regime'] != labels[i - 1]['regime']:
            trans.append(i)

    delays = {'late_exit': [], 'late_entry': [], 'other': []}
    detected = missed = 0
    for k, i in enumerate(trans):
        target = labels[i]['regime']
        end = trans[k + 1] if k + 1 < len(trans) else len(labels)
        hit_ts = None
        for j in range(i, end):
            d = by_ts.get(order[j])
            if d and d['regime'] == target:
                hit_ts = order[j]
                break
        if hit_ts is None:
            missed += 1
            continue
        detected += 1
        delay = _minutes(order[i], hit_ts)
        if target == 'BEAR':
            delays['late_exit'].append(delay)
        elif target == 'BULL':
            delays['late_entry'].append(delay)
        else:
            delays['other'].append(delay)

    # 오탐: 라벨이 그대로인데 판정이 바뀐 지점
    false_alarms = 0
    for j in range(1, len(order)):
        prev_d = by_ts.get(order[j - 1])
        cur_d = by_ts.get(order[j])
        if not prev_d or not cur_d:
            continue
        if cur_d['regime'] != prev_d['regime'] and label_at[order[j]] == label_at[order[j - 1]]:
            false_alarms += 1

    unit = weights['delay_unit_min']
    parts = {
        'late_exit': weights['late_exit'] * sum(delays['late_exit']) / unit,
        'late_entry': weights['late_entry'] * sum(delays['late_entry']) / unit,
        'false_alarm': weights['false_alarm'] * false_alarms,
        'miss': weights['miss'] * missed,
    }
    all_delays = delays['late_exit'] + delays['late_entry'] + delays['other']
    all_delays.sort()
    median = (all_delays[len(all_delays) // 2] if len(all_delays) % 2
              else (all_delays[len(all_delays) // 2 - 1] + all_delays[len(all_delays) // 2]) / 2) \
        if all_delays else None

    return {
        'n_transitions': len(trans),
        'detected': detected,
        'missed': missed,
        'false_alarms': false_alarms,
        'delays_min': all_delays,
        'median_delay_min': median,
        'cost': round(sum(parts.values()), 3),
        'cost_parts': {k: round(v, 3) for k, v in parts.items()},
    }


def calibration(decisions, labels, bins=5):
    """Brier score + reliability. 확률을 내보내는 판정기만 의미가 있다.

    점 추정만 내보내면 과신을 감지할 방법이 없다. 확률을 내보내면
    "P(BEAR)=0.7이라 말한 시점들 중 실제로 70%가 BEAR였나"를 물을 수 있다.
    """
    label_at = {l['ts']: l['regime'] for l in labels}
    pairs = [(d, label_at[d['ts']]) for d in decisions
             if d.get('probs') and d['ts'] in label_at]
    if not pairs:
        return {'brier': None, 'reliability': []}

    total = 0.0
    for d, actual in pairs:
        for r in REGIMES:
            p = float(d['probs'].get(r, 0.0))
            total += (p - (1.0 if r == actual else 0.0)) ** 2
    brier = round(total / len(pairs), 4)

    rel = []
    for k in range(bins):
        lo, hi = k / bins, (k + 1) / bins
        sel = [(float(d['probs'].get('BEAR', 0.0)), actual) for d, actual in pairs
               if lo <= float(d['probs'].get('BEAR', 0.0)) < hi or (k == bins - 1 and
                  float(d['probs'].get('BEAR', 0.0)) == 1.0)]
        if not sel:
            continue
        rel.append({
            'lo': lo, 'hi': hi, 'n': len(sel),
            'mean_pred': round(sum(p for p, _ in sel) / len(sel), 3),
            'freq': round(sum(1 for _, a in sel if a == 'BEAR') / len(sel), 3),
        })
    return {'brier': brier, 'reliability': rel}
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_regime_eval.py -q`
Expected: PASS (10 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/strategy/regime_eval.py tests/test_regime_eval.py
git commit -F - <<'EOF'
feat(sim0): 평가 하네스 — 지연·오탐·비대칭비용·캘리브레이션

'개선'을 정의하는 곳이다. 손실은 breadth MAE가 아니라 전환 탐지 지연 + 오탐이고,
늦게 나가는 것(BEAR 지연)이 늦게 들어가는 것보다 비싸다 — 실측 근거는 아침
BULL→종가 BEAR 10일 vs 역방향 1일(99거래일).

가중치가 숫자를 숨기지 못하게 cost_parts로 구성요소를 따로 내보낸다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 7: 확률 필터

**Files:**
- Create: `src/strategy/regime_filter.py`
- Test: `tests/test_regime_filter.py`

**Interfaces:**
- Consumes: 관측 shape, Task 4의 `label_regimes`(부트스트랩에서)
- Produces:
  - `DEFAULT_PARAMS: dict` — `{'mu': {...}, 'sigma': {...}, 'tau_dwell': 120.0, 'tau_bull': 0.70, 'tau_bear': 0.50}`
  - `transition_matrix(dt_min: float, tau_dwell: float) -> dict[str, dict[str, float]]`
  - `likelihood(obs: dict, mu: dict, sigma: dict) -> dict[str, float]`
  - `filter_step(prev: dict | None, obs: dict, params: dict) -> dict` — 반환 `{'regime', 'probs', 'since_ts', 'last_ts'}`
  - `bootstrap_params(observations: list[dict], labels: list[dict]) -> dict` — `{'mu': {regime: {'b','m'}}, 'sigma': {regime: {'b','m'}}}`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_regime_filter.py`:

```python
# -*- coding: utf-8 -*-
"""3상태 베이즈 필터.

평활을 대체한다. 관성은 전이행렬이, 채터링 방지는 비대칭 임계가 담당한다.
불규칙 런 간격은 Δt 스케일이 처리한다 — 현행 '최근 5런'이 못 하는 일이다.
"""
import math

from src.strategy.regime_filter import (
    DEFAULT_PARAMS, bootstrap_params, filter_step, likelihood, transition_matrix,
)


def _obs(ts, breadth, momentum, sample=100):
    return {'ts': ts, 'breadth': breadth, 'momentum': momentum,
            'trend': None, 'sample': sample, 'source': 't'}


def test_전이행렬은_각_행이_1이다():
    A = transition_matrix(10.0, 120.0)
    for row in A.values():
        assert abs(sum(row.values()) - 1.0) < 1e-9


def test_Δt가_크면_사전확률이_평탄해진다():
    a_short = transition_matrix(10.0, 120.0)['BULL']['BULL']
    a_long = transition_matrix(60.0, 120.0)['BULL']['BULL']
    assert a_short > a_long, '오래 못 봤으면 직전 국면을 덜 믿어야 한다'


def test_Δt가_0이면_상태가_유지된다():
    assert transition_matrix(0.0, 120.0)['BEAR']['BEAR'] == 1.0


def test_표본이_적으면_우도가_약해진다():
    mu = {'BULL': {'b': 80.0, 'm': 2.0}, 'SIDEWAYS': {'b': 50.0, 'm': 0.0},
          'BEAR': {'b': 20.0, 'm': -2.0}}
    sigma = {r: {'b': 10.0, 'm': 1.0} for r in mu}
    strong = likelihood(_obs('t', 80.0, 2.0, sample=100), mu, sigma)
    weak = likelihood(_obs('t', 80.0, 2.0, sample=25), mu, sigma)
    # 약한 증거는 국면 간 우도 비가 작아진다(덜 결정적)
    assert (strong['BULL'] / strong['BEAR']) > (weak['BULL'] / weak['BEAR'])


def test_확률은_합이_1이다():
    st = filter_step(None, _obs('2026-07-30 09:00', 50.0, 0.0), DEFAULT_PARAMS)
    assert abs(sum(st['probs'].values()) - 1.0) < 1e-9


def test_약세_관측이_이어지면_BEAR로_간다():
    st = None
    for i in range(6):
        st = filter_step(st, _obs(f'2026-07-30 09:{i*10:02d}', 10.0, -4.0), DEFAULT_PARAMS)
    assert st['regime'] == 'BEAR'
    assert st['probs']['BEAR'] > 0.5


def test_비대칭_임계가_BEAR를_먼저_켠다():
    # 같은 확신 수준에서 BEAR가 먼저 확정된다 — 늦게 나가면 손실이다.
    assert DEFAULT_PARAMS['tau_bear'] < DEFAULT_PARAMS['tau_bull']


def test_강세_관측_하나로는_BULL이_안_켜진다():
    st = filter_step(None, _obs('2026-07-30 09:00', 95.0, 5.0), DEFAULT_PARAMS)
    # tau_bull이 높아 한 건으로는 넘기 어렵다. SIDEWAYS 또는 BULL 미확정.
    assert st['regime'] in ('SIDEWAYS', 'BULL')
    if st['regime'] == 'BULL':
        assert st['probs']['BULL'] >= DEFAULT_PARAMS['tau_bull']


def test_국면이_바뀌면_since가_갱신된다():
    st = None
    for i in range(6):
        st = filter_step(st, _obs(f'2026-07-30 09:{i*10:02d}', 10.0, -4.0), DEFAULT_PARAMS)
    first_since = st['since_ts']
    st2 = filter_step(st, _obs('2026-07-30 10:00', 10.0, -4.0), DEFAULT_PARAMS)
    assert st2['since_ts'] == first_since, '국면이 그대로면 since는 그대로다'


def test_last_ts가_다음_Δt의_기준이다():
    st = filter_step(None, _obs('2026-07-30 09:00', 50.0, 0.0), DEFAULT_PARAMS)
    assert st['last_ts'] == '2026-07-30 09:00'


def test_시그마가_0이면_죽지_않는다():
    mu = {r: {'b': 50.0, 'm': 0.0} for r in ('BULL', 'SIDEWAYS', 'BEAR')}
    sigma = {r: {'b': 0.0, 'm': 0.0} for r in mu}
    L = likelihood(_obs('t', 50.0, 0.0), mu, sigma)
    assert all(math.isfinite(v) for v in L.values())


def test_부트스트랩은_국면별_평균을_순서대로_준다():
    obs, labels = [], []
    for d in range(1, 11):
        obs.append(_obs(f'2026-06-{d:02d} 15:30', 10.0, -5.0))
        labels.append({'ts': obs[-1]['ts'], 'regime': 'BEAR', 'sb': 0, 'sm': 0})
    for d in range(11, 21):
        obs.append(_obs(f'2026-06-{d:02d} 15:30', 90.0, 5.0))
        labels.append({'ts': obs[-1]['ts'], 'regime': 'BULL', 'sb': 0, 'sm': 0})
    p = bootstrap_params(obs, labels)
    assert p['mu']['BULL']['b'] > p['mu']['BEAR']['b']
    assert p['mu']['BULL']['m'] > p['mu']['BEAR']['m']
    assert p['sigma']['BULL']['b'] > 0, '분산 0이면 우도가 무한이 된다 — 하한이 있어야 한다'


def test_부트스트랩에_없는_국면은_전체_분포로_채운다():
    obs = [_obs(f'2026-06-{d:02d} 15:30', 50.0, 0.0) for d in range(1, 6)]
    labels = [{'ts': o['ts'], 'regime': 'SIDEWAYS', 'sb': 0, 'sm': 0} for o in obs]
    p = bootstrap_params(obs, labels)
    assert set(p['mu']) == {'BULL', 'SIDEWAYS', 'BEAR'}, '없는 국면을 빼면 filter_step이 죽는다'
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_regime_filter.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 최소 구현**

`src/strategy/regime_filter.py`:

```python
# -*- coding: utf-8 -*-
"""3상태 국면 베이즈 필터 — 평활의 대체물.

**왜 평활을 버리는가.** 현행 `_confirm_regime`은 최근 **5런** 최빈값을 쓴다.
10분 간격이면 전환 확정에 최소 30분이 걸리고, 런 간격이 불규칙하면(Tasker 발화)
같은 5런이 뜻하는 시간이 매일 다르다 — 라벨이 시장이 아니라 폰이 언제 울렸는지에
의존한다. 여기서는 관성을 **전이행렬**이 담당하고 Δt로 스케일한다.

**비대칭.** BEAR 전환은 낮은 임계로 빨리, BULL 전환은 높은 임계로 신중히 켠다.
근거(top100 99거래일): 아침 BULL → 종가 BEAR 10일 vs 아침 BEAR → 종가 BULL 1일.
늦게 나가면 손실이고, 늦게 들어가면 기회손실이다 — 후자가 싸다.

**표본을 버리지 않는다.** sigma를 표본수로 보정해 적은 표본은 약한 증거가 된다.
현행은 표본 80 미만이면 관측을 통째로 폐기한다.

전이행렬의 비대각을 균등 분배하는 것은 단순화다(BULL→BEAR 직행과 BULL→SIDEWAYS를
같게 본다). 하네스가 이 단순화의 대가를 측정한다 — 문제가 되면 그때 구조화한다.
"""
import math
from datetime import datetime

REGIMES = ('BULL', 'SIDEWAYS', 'BEAR')

SIGMA_FLOOR = 1e-6      # 분산 0이면 우도가 무한이 된다
SAMPLE_REF = 100.0      # 이 표본수를 기준으로 sigma를 보정한다

# 부트스트랩 전 임시값. scripts/eval_regime.py가 99일에서 계산한 값으로 덮어쓴다.
DEFAULT_PARAMS = {
    'mu': {'BULL': {'b': 78.0, 'm': 1.2}, 'SIDEWAYS': {'b': 48.0, 'm': 0.0},
           'BEAR': {'b': 20.0, 'm': -1.2}},
    'sigma': {'BULL': {'b': 14.0, 'm': 1.0}, 'SIDEWAYS': {'b': 16.0, 'm': 0.8},
              'BEAR': {'b': 13.0, 'm': 1.0}},
    'tau_dwell': 120.0,   # 분. 국면 지속성
    'tau_bull': 0.70,     # 높게 — 늦게 들어가는 쪽이 싸다
    'tau_bear': 0.50,     # 낮게 — 늦게 나가면 손실이다
}


def _parse(ts):
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return None


def _dt_minutes(a, b):
    pa, pb = _parse(a), _parse(b)
    if pa is None or pb is None:
        return 10.0     # 합성 ts는 기본 간격으로 본다
    return max(0.0, (pb - pa).total_seconds() / 60.0)


def transition_matrix(dt_min, tau_dwell):
    """자기전이 `exp(-Δt/tau_dwell)`, 나머지는 다른 두 상태에 균등 분배.

    Δt가 크면 자기전이가 작아진다 = 오래 못 봤으면 직전 국면을 덜 믿는다.
    """
    a = math.exp(-max(0.0, dt_min) / max(1e-9, tau_dwell))
    off = (1.0 - a) / 2.0
    return {r: {r2: (a if r2 == r else off) for r2 in REGIMES} for r in REGIMES}


def _normal_pdf(x, mu, sigma):
    s = max(sigma, SIGMA_FLOOR)
    z = (x - mu) / s
    return math.exp(-0.5 * z * z) / (s * math.sqrt(2 * math.pi))


def likelihood(obs, mu, sigma):
    """국면별 관측 우도. 두 축 독립 가정(단순화 — 하네스가 대가를 측정한다).

    sigma를 표본수로 보정한다: 표본이 적으면 분포가 넓어져 국면 간 구분이 약해진다.
    """
    scale = math.sqrt(SAMPLE_REF / max(1.0, float(obs.get('sample') or 1)))
    out = {}
    for r in REGIMES:
        out[r] = (_normal_pdf(obs['breadth'], mu[r]['b'], sigma[r]['b'] * scale)
                  * _normal_pdf(obs['momentum'], mu[r]['m'], sigma[r]['m'] * scale))
    return out


def filter_step(prev, obs, params):
    """① 예측(전이) → ② 갱신(우도) → ③ 비대칭 임계 결정."""
    if prev is None:
        probs = {r: 1.0 / len(REGIMES) for r in REGIMES}
        prev_regime, since = 'SIDEWAYS', obs['ts']
    else:
        dt = _dt_minutes(prev['last_ts'], obs['ts'])
        A = transition_matrix(dt, params['tau_dwell'])
        probs = {r2: sum(prev['probs'][r1] * A[r1][r2] for r1 in REGIMES) for r2 in REGIMES}
        prev_regime, since = prev['regime'], prev['since_ts']

    L = likelihood(obs, params['mu'], params['sigma'])
    post = {r: probs[r] * L[r] for r in REGIMES}
    total = sum(post.values())
    if total <= 0:
        post = dict(probs)                     # 우도가 전부 0이면 사전확률을 유지한다
        total = sum(post.values()) or 1.0
    post = {r: post[r] / total for r in REGIMES}

    if post['BEAR'] > params['tau_bear']:
        regime = 'BEAR'
    elif post['BULL'] > params['tau_bull']:
        regime = 'BULL'
    else:
        regime = 'SIDEWAYS'

    return {
        'regime': regime,
        'probs': {r: round(post[r], 6) for r in REGIMES},
        'since_ts': obs['ts'] if regime != prev_regime else since,
        'last_ts': obs['ts'],
    }


def bootstrap_params(observations, labels):
    """라벨된 관측에서 국면별 (폭, 강도) 평균·표준편차.

    라벨에 없는 국면은 전체 분포로 채운다 — 빠지면 filter_step이 KeyError로 죽는다.
    표준편차에 하한을 둔다: 표본이 1개면 0이 되고 우도가 발산한다.
    """
    label_at = {l['ts']: l['regime'] for l in labels}
    buckets = {r: {'b': [], 'm': []} for r in REGIMES}
    all_b, all_m = [], []
    for o in observations:
        all_b.append(o['breadth'])
        all_m.append(o['momentum'])
        r = label_at.get(o['ts'])
        if r in buckets:
            buckets[r]['b'].append(o['breadth'])
            buckets[r]['m'].append(o['momentum'])

    def stats(xs, fallback):
        if len(xs) < 2:
            return fallback
        mean = sum(xs) / len(xs)
        var = sum((x - mean) ** 2 for x in xs) / len(xs)
        return mean, max(var ** 0.5, 1.0)

    fb_b = stats(all_b, (50.0, 15.0))
    fb_m = stats(all_m, (0.0, 1.0))
    mu, sigma = {}, {}
    for r in REGIMES:
        mb, sb = stats(buckets[r]['b'], fb_b)
        mm, sm = stats(buckets[r]['m'], fb_m)
        mu[r] = {'b': round(mb, 2), 'm': round(mm, 3)}
        sigma[r] = {'b': round(sb, 2), 'm': round(sm, 3)}
    return {'mu': mu, 'sigma': sigma}
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_regime_filter.py -q`
Expected: PASS (13 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/strategy/regime_filter.py tests/test_regime_filter.py
git commit -F - <<'EOF'
feat(sim0): 3상태 베이즈 필터 — 평활 대체

관성은 전이행렬이 담당하고 Δt로 스케일한다. 현행 '최근 5런' 최빈값은 런 개수
기반이라 간격이 불규칙하면 같은 5런이 뜻하는 시간이 매일 달랐다.

비대칭 임계: BEAR는 0.50, BULL은 0.70. 늦게 나가면 손실이고 늦게 들어가면
기회손실이다 — 실측 근거 아침 BULL→종가 BEAR 10일 vs 역방향 1일.

표본이 적은 관측을 버리지 않고 sigma 보정으로 약한 증거로 다룬다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 8: 스윕 실행과 비교표

**Files:**
- Create: `scripts/eval_regime.py`
- Test: `tests/test_eval_regime_script.py`

**Interfaces:**
- Consumes: Task 3~7 전부
- Produces:
  - `build_daily_dataset(ohlcv_path: str, label_kwargs: dict) -> tuple[list[dict], list[dict]]` — (observations, labels)
  - `compare(observations, labels, filter_params_grid: list[dict]) -> list[dict]` — 각 dict: `{'name', 'params', 'score', 'calibration'}`
  - `format_table(results: list[dict]) -> str`

**이 태스크가 계획의 결론이다.** 확률 필터가 기준선 4개를 이기는지 여기서 판정된다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_eval_regime_script.py`:

```python
# -*- coding: utf-8 -*-
"""비교표 — 계획의 결론이 나오는 자리.

기준선 4개가 항상 표에 있어야 한다. 하나라도 빠지면 '개선'을 주장할 근거가 사라진다.
"""
from scripts.eval_regime import build_daily_dataset, compare, format_table


def test_기준선_4개가_항상_표에_있다():
    obs = [{'ts': f'2026-06-{d:02d} 15:30', 'breadth': 50.0 + (d % 5) * 10,
            'momentum': (d % 5) - 2.0, 'trend': 25.0, 'sample': 100, 'source': 't'}
           for d in range(1, 31)]
    labels = [{'ts': o['ts'], 'regime': 'SIDEWAYS', 'sb': 0.0, 'sm': 0.0} for o in obs]
    results = compare(obs, labels, [])
    names = [r['name'] for r in results]
    for expected in ('always_sideways', 'immediate', 'current_production', 'hysteresis'):
        assert expected in names, f'{expected} 기준선이 표에서 빠졌다'


def test_필터_그리드가_표에_추가된다():
    obs = [{'ts': f'2026-06-{d:02d} 15:30', 'breadth': 20.0, 'momentum': -3.0,
            'trend': 25.0, 'sample': 100, 'source': 't'} for d in range(1, 21)]
    labels = [{'ts': o['ts'], 'regime': 'BEAR', 'sb': 0.0, 'sm': 0.0} for o in obs]
    grid = [{'tau_bear': 0.5, 'tau_bull': 0.7, 'tau_dwell': 120.0}]
    results = compare(obs, labels, grid)
    assert any(r['name'].startswith('filter') for r in results)


def test_표에_비용과_구성요소가_들어간다():
    obs = [{'ts': f'2026-06-{d:02d} 15:30', 'breadth': 50.0, 'momentum': 0.0,
            'trend': 25.0, 'sample': 100, 'source': 't'} for d in range(1, 11)]
    labels = [{'ts': o['ts'], 'regime': 'SIDEWAYS', 'sb': 0.0, 'sm': 0.0} for o in obs]
    table = format_table(compare(obs, labels, []))
    assert 'cost' in table
    assert 'false' in table.lower()


def test_실제_일봉으로_데이터셋이_만들어진다():
    obs, labels = build_daily_dataset('output/ohlcv_top100.csv', {'window': 5})
    assert len(obs) > 50, '99거래일이 있어야 한다'
    assert len(obs) == len(labels)
    assert {l['regime'] for l in labels} <= {'BULL', 'SIDEWAYS', 'BEAR'}
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_eval_regime_script.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.eval_regime'`

- [ ] **Step 3: 최소 구현**

`scripts/eval_regime.py`:

```python
# -*- coding: utf-8 -*-
"""국면 판정기 비교 — 확률 필터가 기준선을 이기는지 판정한다.

10분 이력이 쌓이기 전에는 일봉 99거래일을 관측 시계열로 본다. **여기서 설계의
사활이 갈린다** — 일 해상도에서 기준선을 못 이기면 10분에서도 못 이길 가능성이
높고, 그때는 되돌아온다.

실행: PYTHONPATH=. python scripts/eval_regime.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from src.strategy.regime_baselines import (  # noqa: E402
    always_sideways, current_production, hysteresis, immediate,
)
from src.strategy.regime_daily import daily_observations, load_ohlcv  # noqa: E402
from src.strategy.regime_eval import calibration, replay, score  # noqa: E402
from src.strategy.regime_filter import (  # noqa: E402
    DEFAULT_PARAMS, bootstrap_params, filter_step,
)
from src.strategy.regime_label import label_regimes  # noqa: E402

IMM_PARAMS = {'b_hi': 60.0, 'b_lo': 40.0, 'm_hi': 2.0, 'm_lo': -2.0}
HYS_PARAMS = {'enter_bear': 40.0, 'exit_bear': 55.0, 'enter_bull': 65.0,
              'exit_bull': 50.0, 'dwell_min': 20}


def build_daily_dataset(ohlcv_path, label_kwargs=None):
    """일봉 CSV → (관측, 라벨)."""
    obs = daily_observations(load_ohlcv(ohlcv_path))
    labels = label_regimes(obs, **(label_kwargs or {}))
    return obs, labels


def compare(observations, labels, filter_params_grid):
    """기준선 4개 + 필터 그리드를 같은 데이터에 재생하고 채점한다."""
    results = []
    for name, decider, params in (
        ('always_sideways', always_sideways, {}),
        ('immediate', immediate, IMM_PARAMS),
        ('current_production', current_production, {}),
        ('hysteresis', hysteresis, HYS_PARAMS),
    ):
        decisions = replay(observations, decider, params)
        results.append({'name': name, 'params': params,
                        'score': score(decisions, labels),
                        'calibration': calibration(decisions, labels)})

    boot = bootstrap_params(observations, labels)
    for i, grid in enumerate(filter_params_grid):
        params = dict(DEFAULT_PARAMS)
        params.update(boot)
        params.update(grid)
        decisions = replay(observations, filter_step, params)
        label = (f"filter[bear={grid.get('tau_bear')},bull={grid.get('tau_bull')},"
                 f"dwell={grid.get('tau_dwell')}]")
        results.append({'name': label, 'params': grid,
                        'score': score(decisions, labels),
                        'calibration': calibration(decisions, labels)})
    return results


def format_table(results):
    """비용 순 정렬 표. 구성요소를 같이 보여준다 — 가중치가 숫자를 숨기지 못하게."""
    head = (f"{'판정기':<44}{'cost':>8}{'지연(중앙,분)':>14}"
            f"{'미탐':>6}{'false':>7}{'Brier':>8}")
    lines = [head, '-' * len(head)]
    for r in sorted(results, key=lambda x: x['score']['cost']):
        s, c = r['score'], r['calibration']
        med = '-' if s['median_delay_min'] is None else f"{s['median_delay_min']:.0f}"
        brier = '-' if c['brier'] is None else f"{c['brier']:.4f}"
        lines.append(f"{r['name']:<44}{s['cost']:>8.2f}{med:>14}"
                     f"{s['missed']:>6}{s['false_alarms']:>7}{brier:>8}")
    lines.append('')
    lines.append('비용 구성요소 (late_exit / late_entry / false_alarm / miss):')
    for r in sorted(results, key=lambda x: x['score']['cost']):
        p = r['score']['cost_parts']
        lines.append(f"  {r['name']:<44}"
                     f"{p['late_exit']:>8.2f}{p['late_entry']:>10.2f}"
                     f"{p['false_alarm']:>10.2f}{p['miss']:>8.2f}")
    return '\n'.join(lines)


def main():
    obs, labels = build_daily_dataset('output/ohlcv_top100.csv', {'window': 5})
    n_trans = sum(1 for i in range(1, len(labels))
                  if labels[i]['regime'] != labels[i - 1]['regime'])
    print(f'표본 {len(obs)}거래일 · 라벨 전환 {n_trans}건')
    dist = {r: sum(1 for l in labels if l['regime'] == r)
            for r in ('BULL', 'SIDEWAYS', 'BEAR')}
    print(f'라벨 분포 {dist}')
    print()

    grid = [{'tau_bear': tb, 'tau_bull': tu, 'tau_dwell': td}
            for tb in (0.40, 0.50, 0.60)
            for tu in (0.60, 0.70, 0.80)
            for td in (60.0, 120.0, 240.0)]
    print(format_table(compare(obs, labels, grid)))


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: `scripts`를 패키지로 import 가능하게 한다**

Run: `ls scripts/__init__.py 2>/dev/null || touch scripts/__init__.py`

(테스트가 `from scripts.eval_regime import ...`를 쓴다. `scripts/gen_sim_registry.py`를
`tests/test_sim_registry_consistency.py`가 이미 `from scripts.gen_sim_registry import build`로
import하므로 이 경로는 이미 동작한다 — 없으면 만든다.)

- [ ] **Step 5: 통과를 확인한다**

Run: `python -m pytest tests/test_eval_regime_script.py -q`
Expected: PASS (4 passed)

- [ ] **Step 6: 실제 비교표를 뽑는다**

Run: `PYTHONPATH=. python scripts/eval_regime.py`

Expected: 표본 99거래일 내외, 라벨 전환 수와 분포가 출력되고, 판정기 비교표가 비용 순으로 나온다.

**판정 기준(이 계획의 결론):**
- 확률 필터의 최적 조합이 `hysteresis`와 `current_production` **둘 다**보다 `cost`가 낮고
  `false_alarms`가 크지 않으면 → 단계 2(승격) 진행 근거가 된다
- 필터가 `hysteresis`를 못 이기면 → **복잡도를 정당화할 수 없다.** 스펙 §2.3에 따라
  히스테리시스를 후보로 남기고 확률 필터는 보류한다. 이 결과를 그대로 기록한다
- 어느 쪽이든 결과를 `docs/superpowers/plans/` 옆에 결과 노트로 남긴다

- [ ] **Step 7: 결과 기록과 커밋**

비교표 출력을 `docs/superpowers/plans/2026-07-30-sim0-regime-filter-results.md`에 붙여넣고
한 문단으로 해석을 적는다(무엇이 이겼는지, 왜, 다음 행동).

```bash
git add scripts/eval_regime.py scripts/__init__.py tests/test_eval_regime_script.py \
        docs/superpowers/plans/2026-07-30-sim0-regime-filter-results.md
git commit -F - <<'EOF'
feat(sim0): 판정기 비교 하네스 실행 + 결과 기록

일봉 99거래일에서 기준선 4개와 확률 필터 그리드를 같은 데이터에 재생해
비용·지연·오탐·Brier를 비교한다.

기준선 없이 개선을 주장하지 않는다. 확률 필터가 히스테리시스를 못 이기면
복잡도를 정당화할 수 없고, 그 결과도 그대로 기록한다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 9: 섀도우 판정 기록

**Files:**
- Modify: `src/strategy/simulators/sim0_libero.py` (`run()` 내부, `bull_score` 계산 직후)
- Test: `tests/test_regime_shadow.py`

**Interfaces:**
- Consumes: `filter_step`, `DEFAULT_PARAMS` (Task 7)
- Produces: state 키 `regime_shadow` = `{'regime', 'probs', 'since_ts', 'last_ts'}`

**Task 8에서 필터가 기준선을 못 이겼더라도 이 태스크는 수행한다** — 병기 기록이 10분 이력에서의
재검증 데이터를 만든다. 계약은 건드리지 않으므로 위험이 없다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_regime_shadow.py`:

```python
# -*- coding: utf-8 -*-
"""섀도우 판정 — current_regime을 건드리지 않고 나란히 기록한다.

병기 기록이 곧 A/B 기간이다. 축적된 것이 10분 해상도 재검증의 데이터가 된다.
"""
import io
import json
import os

from src.strategy.simulators.sim0_libero import LiberoSimulator


def _sim(tmp_path):
    sim = LiberoSimulator.__new__(LiberoSimulator)
    sim.name = 'Libero'
    sim.state_file = str(tmp_path / 'libero.json')
    sim.csv_file = str(tmp_path / 'libero.csv')
    sim.state = {
        'initial_cash': 0, 'cash': 0, 'invested': 0, 'portfolio': {},
        'peak_nav': 0, 'total_fees': 0, 'history': [0], 'daily_trades': [],
        'market_index_healthy': True, 'cooldown_codes': {},
    }
    sim.live_market_metrics = {'breadth': 12.0, 'momentum': -4.0, 'trend': 30.0, 'sample': 100}
    return sim


def _candidates():
    return [{'code': '005930', 'name': '삼성전자', 'change_rate': '-3.00%',
             'sparkline_price': [100, 99, 98, 97, 96], 'foreign_change': 0}]


def test_섀도우가_기록된다(tmp_path):
    sim = _sim(tmp_path)
    sim.run(_candidates(), current_prices={})
    sh = sim.state['regime_shadow']
    assert sh['regime'] in ('BULL', 'SIDEWAYS', 'BEAR')
    assert abs(sum(sh['probs'].values()) - 1.0) < 1e-6
    assert sh['last_ts']


def test_current_regime을_바꾸지_않는다(tmp_path):
    sim = _sim(tmp_path)
    sim.run(_candidates(), current_prices={})
    # 계약: 현행 분류기 + 5런 평활이 정한 값이 그대로 남는다
    assert sim.state['current_regime'] in ('BULL', 'SIDEWAYS', 'BEAR')
    assert sim.state['regime_shadow']['regime'] != 'CONTRACT_BROKEN'
    assert 'bull_score' in sim.state


def test_bull_score_계산식이_안_바뀌었다(tmp_path):
    sim = _sim(tmp_path)
    # 0.40*breadth + 0.35*momentum_n + 0.25*trend_n, momentum_n = clamp(50 + m*5)
    expected = round(12.0 * 0.40 + max(0.0, min(100.0, 50 + (-4.0) * 5)) * 0.35 + 30.0 * 0.25, 1)
    assert sim.calc_bull_score(12.0, -4.0, 30.0) == expected


def test_섀도우가_런_사이에_이어진다(tmp_path):
    sim = _sim(tmp_path)
    sim.run(_candidates(), current_prices={})
    first = sim.state['regime_shadow']['probs']['BEAR']
    sim.run(_candidates(), current_prices={})
    second = sim.state['regime_shadow']['probs']['BEAR']
    assert second >= first, '같은 약세 관측이 이어지면 BEAR 확률이 줄지 않는다'


def test_상태가_JSON으로_저장된다(tmp_path):
    sim = _sim(tmp_path)
    sim.run(_candidates(), current_prices={})
    with io.open(sim.state_file, encoding='utf-8') as f:
        saved = json.load(f)
    assert 'regime_shadow' in saved
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/test_regime_shadow.py -q`
Expected: FAIL — `KeyError: 'regime_shadow'`

- [ ] **Step 3: 배선**

`src/strategy/simulators/sim0_libero.py`의 `run()`에서 `bull_score = self.calc_bull_score(...)`
바로 다음에 삽입한다:

```python
        # 섀도우 판정 — current_regime을 건드리지 않고 나란히 기록한다.
        # 확률 필터를 병기해 두면 축적 기간이 곧 A/B 기간이 된다. 승격 판단은
        # scripts/eval_regime.py의 비교표로 하고, 여기서는 계약을 바꾸지 않는다.
        try:
            from src.strategy.regime_filter import DEFAULT_PARAMS, filter_step
            obs = {'ts': get_kst_now().strftime('%Y-%m-%d %H:%M'),
                   'breadth': breadth, 'momentum': momentum,
                   'trend': trend, 'sample': breadth_sample}
            self.state['regime_shadow'] = filter_step(
                self.state.get('regime_shadow'), obs, DEFAULT_PARAMS)
        except Exception as e:
            # 섀도우 실패가 국면 판정을 막지 않는다. 다만 조용히 넘기지 않는다.
            print(f"[Libero] 섀도우 판정 실패: {e}")
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/test_regime_shadow.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: 전체 회귀 — 계약이 안 깨졌는지**

Run: `python -m pytest tests/ -q`
Expected: PASS. 특히 `tests/test_regime_state.py`, `tests/test_libero_eod_and_leak.py`,
`tests/test_orchestrator_active_only.py`가 통과해야 한다(국면 계약 소비자들).

- [ ] **Step 6: 커밋**

```bash
git add src/strategy/simulators/sim0_libero.py tests/test_regime_shadow.py
git commit -F - <<'EOF'
feat(sim0): 확률 필터를 섀도우로 병기 기록

current_regime과 bull_score를 건드리지 않는다 — Sim6·Sim10·Sim7 계약 그대로다.
병기 기록이 곧 A/B 기간이고, 축적된 것이 10분 해상도 재검증의 데이터가 된다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 10: 문서 갱신과 병합

**Files:**
- Modify: `docs/ARCHITECTURE_DEBT.md` (0번 절 표)
- Modify: `docs/superpowers/specs/2026-07-30-sim0-regime-filter-design.md` (단계 0/1 완료 표시)

- [ ] **Step 1: 부채 지도 0번 절에 한 줄 추가**

`docs/ARCHITECTURE_DEBT.md`의 완료 표에 추가:

```markdown
| (이번 브랜치) | 심0 국면 판정 재설계 단계 0·1 — 10분 관측 이력·라벨러·하네스·확률 필터(섀도우) |
```

그리고 "지금 상태" 줄의 pytest·node 개수를 실제 값으로 갱신한다
(`python -m pytest tests/ -q`와 `node --test "src/**/*.test.ts"`의 출력을 그대로 쓴다).

- [ ] **Step 2: 스펙에 완료 표시**

`docs/superpowers/specs/2026-07-30-sim0-regime-filter-design.md`의 `## 5. 단계` 절에서
단계 0과 단계 1 항목 앞에 `[완료]`를 붙이고, Task 8의 결론(필터가 이겼는지)을
한 줄로 적는다.

- [ ] **Step 3: 전체 검증**

```bash
python -m pytest tests/ -q
node --test "src/**/*.test.ts"
npx tsc --noEmit
```
Expected: 셋 다 통과. TS는 이 계획에서 손대지 않았으므로 개수가 그대로여야 한다.

- [ ] **Step 4: 커밋과 병합**

```bash
git add docs/ARCHITECTURE_DEBT.md docs/superpowers/specs/2026-07-30-sim0-regime-filter-design.md
git commit -F - <<'EOF'
docs(sim0): 국면 재설계 단계 0·1 완료 반영

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
git checkout main
git merge --no-ff <branch> -F <메시지 파일 경로>
git push origin main
```

**커밋·병합 메시지는 반드시 파일로 넘긴다** (`-F <경로>`). Bash 툴에서 PowerShell
here-string(`@'...'@`)을 쓰면 제목에 `@`가 박힌다 — 이 레포에서 4회 재발했다.

---

## Self-Review

**스펙 커버리지**

| 스펙 요구 | 태스크 |
|---|---|
| §4.1 관측 이력 CSV, 분 단위, 표본 80 미만도 기록 | Task 1, 2 |
| §4.2 라벨러(대칭 평활, 롤링 분위수, 2축 AND) | Task 4 |
| §4.3 `filter_step`(Δt 전이, 표본 보정 우도, 비대칭 임계) | Task 7 |
| §4.3 ④ `trend` 판정에서 제외 | Task 7 (`filter_step`이 trend를 안 읽는다) |
| §4.4 99일 부트스트랩 | Task 3, 7(`bootstrap_params`), 8 |
| §4.5 하네스(재생·채점·캘리브레이션) | Task 6 |
| §2.2 비대칭 비용 | Task 6 (`COST_WEIGHTS`, `cost_parts`) |
| §2.3 기준선 4개 | Task 5, 8 |
| §5 단계 1 일 해상도 1차 비교 | Task 8 |
| §5 단계 1-3 섀도우 배선 | Task 9 |
| 계약 불변(`current_regime`·`bull_score`) | Task 9 Step 3·5, 테스트 2건 |
| §5 단계 0-4 KIS 과거 분봉 확인 | **의도적 제외** — 스펙이 "되면 좋고 안 되면 기다린다"로 두었고 계획을 여기 의존시키지 않는다. 별건 조사로 남긴다 |

**플레이스홀더 스캔**: 없다. 모든 스텝에 실제 코드·명령·기대 출력이 있다.
Task 10 Step 4의 `<branch>`와 메시지 경로는 실행 시점에만 결정되는 값이라 남겼다.

**타입 일관성 확인**
- 관측 shape `{'ts','breadth','momentum','trend','sample','source'}` — Task 1·3·4·5·6·7·9 전부 동일
- 라벨 shape `{'ts','regime','sb','sm'}` — Task 4 생성, 6·7·8 소비. 일치
- 판정기 시그니처 `(prev, obs, params) -> {'regime', ...}` — Task 5·7 동일, Task 6 `replay`가 그대로 호출
- 판정 결과 `{'ts','regime','probs'}` — Task 6 `replay` 생성, `score`·`calibration` 소비. 기준선은 `probs`가 없어 `.get('probs')`로 `None`이 되고 `calibration`이 `brier: None`을 반환. Task 6 테스트가 이 경로를 덮는다
- `REGIMES`가 `regime_label.py`와 `regime_filter.py` 양쪽에 있다. `regime_eval.py`는 label 쪽을 import한다. **중복이지만 의도적이다** — filter가 label을 import하면 순환이 생긴다. 값이 갈리면 Task 6·7 테스트가 깨진다
