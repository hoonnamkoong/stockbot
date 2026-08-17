# 국면 관측 축적 구조 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관측 이력을 60거래일 천장에서 풀고, 이미 받고 있는 응답에서 8개 열을 더 남긴다.

**Architecture:** `regime_observations.py`의 스키마를 6열에서 14열로 넓히고 롤링 트림을 제거한다. 파일을 월별로 쪼개되 이 레포에 이미 있는 `rank_snapshot.month_path` 규약을 그대로 쓴다. 수집부는 네이버 응답의 열 위치를 헤더 텍스트로 해석해 신규 열을 채운다. 마지막으로 "언제 학습을 시작하나"에 답하는 읽기 전용 리포트를 추가한다.

**Tech Stack:** Python 3.12, pytest, BeautifulSoup. 새 의존성 없음.

**Spec:** `docs/superpowers/specs/2026-08-17-regime-observation-accumulation-design.md`

**Branch:** `feat/regime-accumulation` (`main`에서 분기)

## Global Constraints

- 기존 6열(`ts_kst, breadth, momentum, trend, sample, source`)의 이름·순서·의미 **불변**. db-data에 426행이 이 스키마로 쌓여 있다.
- `calc_bull_score` · `classify_regime` · `current_regime` 계약 **변경 금지**. 이 계획은 매매 판단을 건드리지 않는다.
- 추가 수집 요청 **0건**. 새 열은 전부 이미 받고 있는 네이버 응답에서 파생한다.
- 가짜 값 금지: 없는 값은 빈 칸으로 남긴다. 저장 계층은 0·평균·직전값으로 대체하지 않는다.
- 룩어헤드 금지: 관측 행은 그 시각에 관측 가능한 것만 담는다. 라벨은 저장하지 않는다.
- 월별 파일명은 `src/data/rank_snapshot.py::month_path`와 같은 이름·같은 시그니처. 새 규약을 지어내지 않는다.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `src/strategy/regime_observations.py` (수정) | 14열 직렬화·파싱·append(멱등)·월별 경로·전체 로드 |
| `src/pipeline/workers/trade_engine.py` (수정) | 네이버 응답 열 해석 + 신규 지표 산출 + append 배선 |
| `scripts/trade_loop.py` (수정) | 배포 매니페스트가 월별 파일명을 런타임에 해석 |
| `scripts/regime_data_status.py` (신규) | 충분성 리포트 — 읽기 전용 |
| `tests/test_regime_observations.py` (수정) | 스키마·월별·트림 제거·결측 왕복 |
| `tests/test_regime_data_status.py` (신규) | 유효 쌍 계산의 날짜 경계·결측 슬롯 |
| `tests/test_trade_loop.py` (수정) | 배포 파생이 쓰기 경로와 일치 |

---

## Task 1: 14열 스키마와 결측 규약

**Files:**
- Modify: `src/strategy/regime_observations.py`
- Test: `tests/test_regime_observations.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `OBS_HEADER: list[str]` — 14개
  - `OBS_EXTRA: tuple[str, ...]` = `('breadth_cap','p10','p25','p75','p90','up','down','turnover')`
  - `format_row(rec: dict) -> list[str]` — **시그니처 변경.** 기존 6-인자 위치 호출을 대체한다
  - `parse_observations(text: str) -> list[dict]` — 레코드 키는 `ts`(= `ts_kst` 열) + 나머지 13개 열 이름 그대로. 없는 열은 `None`
  - `append_observation(path, ts, breadth, momentum, trend, sample, source, extra: dict | None = None) -> bool`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_regime_observations.py`의 `test_헤더가_계약이다`를 아래로 교체하고, 그 아래에 새 테스트들을 추가한다. import 줄에 `OBS_EXTRA`를 더한다.

```python
from src.strategy.regime_observations import (
    MAX_DISTINCT_DATES, OBS_EXTRA, OBS_HEADER, append_observation, format_row,
    parse_observations, trim_to_recent_dates,
)


def test_헤더가_계약이다():
    assert OBS_HEADER == [
        'ts_kst', 'breadth', 'momentum', 'trend', 'sample', 'source',
        'breadth_cap', 'p10', 'p25', 'p75', 'p90', 'up', 'down', 'turnover',
    ], '기존 6열의 이름과 순서는 불변이다 — db-data에 426행이 이 스키마로 쌓여 있다'
    assert list(OBS_EXTRA) == OBS_HEADER[6:]


def test_구_스키마_6열_행을_읽는다():
    # db-data의 아카이브가 이 모양이다. 새 파서가 이걸 못 읽으면 426행이 통째로 사라진다.
    text = 'ts_kst,breadth,momentum,trend,sample,source\n' \
           '2026-08-07 09:01,37.0,0.00,13.1,100,top100_live\n'
    rows = parse_observations(text)
    assert len(rows) == 1
    assert rows[0]['breadth'] == 37.0
    assert rows[0]['trend'] == 13.1
    for col in OBS_EXTRA:
        assert rows[0][col] is None, f'{col}은 없는 것이지 0이 아니다'


def test_신규_열_왕복(tmp_path):
    p = str(tmp_path / 'obs.csv')
    extra = {'breadth_cap': 63.2, 'p10': -2.15, 'p25': -0.80,
             'p75': 1.44, 'p90': 3.07, 'up': 61, 'down': 37, 'turnover': 128450}
    assert append_observation(p, '2026-08-17 09:10', 61.0, 0.42, 44.9, 100,
                              'top100_live', extra=extra) is True
    row = parse_observations(_read(p))[0]
    for col, want in extra.items():
        assert row[col] == want


def test_신규_열이_없으면_빈_칸이고_None으로_읽힌다(tmp_path):
    p = str(tmp_path / 'obs.csv')
    append_observation(p, '2026-08-17 09:10', 61.0, 0.42, 44.9, 100, 'top100_live')
    line = _read(p).strip().splitlines()[1]
    assert line.endswith(',,,,,,,,'), '신규 8열이 빈 칸이어야 한다 — 0으로 채우지 않는다'
    row = parse_observations(_read(p))[0]
    for col in OBS_EXTRA:
        assert row[col] is None


def test_모르는_열은_시끄럽게_거절한다(tmp_path):
    # 오타가 조용히 버려지면 그 기간의 열이 통째로 빈다. 몇 달 뒤에 발견된다.
    import pytest
    p = str(tmp_path / 'obs.csv')
    with pytest.raises(ValueError):
        append_observation(p, '2026-08-17 09:10', 61.0, 0.42, 44.9, 100,
                           'top100_live', extra={'turnovr': 1})


def test_정수열은_소수점_없이_쓴다(tmp_path):
    p = str(tmp_path / 'obs.csv')
    append_observation(p, '2026-08-17 09:10', 61.0, 0.42, 44.9, 100, 'top100_live',
                       extra={'up': 61, 'down': 37, 'turnover': 128450})
    line = _read(p).strip().splitlines()[1]
    assert ',61,37,128450' in line
```

그리고 기존 `test_새_파일은_헤더와_한_행을_쓴다`의 dict 비교와 `test_format_row는_문자열_리스트다`를 아래로 교체한다.

```python
def test_새_파일은_헤더와_한_행을_쓴다(tmp_path):
    p = str(tmp_path / 'obs.csv')
    assert append_observation(p, '2026-07-30 09:10', 51.0, -0.12, 39.0, 100, 'top100_live') is True
    rows = parse_observations(_read(p))
    assert len(rows) == 1
    assert rows[0]['ts'] == '2026-07-30 09:10'
    assert rows[0]['breadth'] == 51.0
    assert rows[0]['momentum'] == -0.12
    assert rows[0]['trend'] == 39.0
    assert rows[0]['sample'] == 100
    assert rows[0]['source'] == 'top100_live'


def test_format_row는_문자열_리스트다():
    rec = {'ts': '2026-07-30 09:10', 'breadth': 51.0, 'momentum': -0.125,
           'trend': None, 'sample': 100, 'source': 'x'}
    assert format_row(rec) == ['2026-07-30 09:10', '51.0', '-0.13', '', '100', 'x',
                               '', '', '', '', '', '', '', '']
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_regime_observations.py -v`
Expected: FAIL — `ImportError: cannot import name 'OBS_EXTRA'`

- [ ] **Step 3: 스키마를 넓힌다**

`src/strategy/regime_observations.py`에서 `OBS_HEADER` 정의를 아래로 교체한다.

```python
OBS_HEADER = [
    'ts_kst', 'breadth', 'momentum', 'trend', 'sample', 'source',
    # 아래 8열은 2026-08 추가. 전부 기존 네이버 응답에서 파생한다(추가 요청 0건).
    # 없으면 빈 칸이다 — 0으로 채우면 '측정 못 함'과 '진짜 0'이 합쳐진다.
    'breadth_cap',                      # 시총가중 상승비율. 동일가중 breadth와 갈리는 날이 전환일이다
    'p10', 'p25', 'p75', 'p90',         # 등락률 분위수. p50은 momentum과 같아 넣지 않는다
    'up', 'down',                       # 상승·하락 종목 수. flat = sample - up - down
    'turnover',                         # Σ(현재가 × 거래량) / 1e8, 억원. 정확한 거래대금이 아닌 근사다
]

OBS_EXTRA = tuple(OBS_HEADER[6:])

# CSV 열 이름 → 레코드 키. ts_kst만 다르다(기존 계약 유지).
_RECORD_KEY = {'ts_kst': 'ts'}

# 열별 소수 자릿수.
_DECIMALS = {'breadth': 1, 'momentum': 2, 'trend': 1, 'breadth_cap': 1,
             'p10': 2, 'p25': 2, 'p75': 2, 'p90': 2}
_INT_COLS = ('sample', 'up', 'down', 'turnover')
_TEXT_COLS = ('ts_kst', 'source')
```

- [ ] **Step 4: `format_row`를 레코드 기반으로 바꾼다**

기존 `format_row`를 아래로 교체한다.

```python
def format_row(rec):
    """레코드 dict → CSV 한 행(문자열 리스트).

    없는 값은 **빈 칸**이다. 0으로 적으면 '측정 못 함'과 '진짜 0'이 한 값이 되고,
    그건 나중에 어떤 방법으로도 되돌릴 수 없다.
    """
    out = []
    for col in OBS_HEADER:
        v = rec.get(_RECORD_KEY.get(col, col))
        if col in _TEXT_COLS:
            out.append('' if v is None else str(v))
        elif v is None:
            out.append('')
        elif col in _INT_COLS:
            out.append(str(int(v)))
        else:
            out.append(_round_str(v, _DECIMALS[col]))
    return out
```

- [ ] **Step 5: 파서를 하위호환으로 바꾼다**

기존 `parse_observations`를 아래로 교체한다.

```python
def _opt(value, cast):
    """빈 칸·부재·파싱 실패는 전부 None. 있는 값만 캐스팅한다."""
    if value is None or value == '':
        return None
    try:
        return cast(value)
    except ValueError:
        return None


def parse_observations(text):
    """CSV 텍스트 → 관측 리스트. 깨진 행은 건너뛰고 나머지를 살린다.

    **구 스키마(6열) 파일도 읽는다.** db-data의 아카이브가 그 모양이고,
    못 읽으면 426행이 통째로 사라진다. 없는 열은 None이다.
    """
    rows = []
    reader = csv.reader(io.StringIO(text.lstrip('﻿')))
    header = None
    for values in reader:
        if not values:
            continue
        if header is None:
            header = [c.strip() for c in values]
            continue
        # 파일 자신의 헤더 길이로 잰다. len(OBS_HEADER)로 재면 6열 아카이브가 통째로 버려진다.
        if len(values) < len(header):
            continue
        rec = dict(zip(header, [v.strip() for v in values]))
        try:
            row = {
                'ts': rec['ts_kst'],
                'breadth': float(rec['breadth']),
                'momentum': float(rec['momentum']),
                'trend': _opt(rec.get('trend'), float),
                'sample': int(rec['sample']),
                'source': rec['source'],
            }
        except (KeyError, ValueError):
            continue
        for col in OBS_EXTRA:
            row[col] = _opt(rec.get(col), int if col in _INT_COLS else float)
        rows.append(row)
    return rows
```

- [ ] **Step 6: `append_observation`이 신규 열을 받게 한다**

기존 `append_observation`을 아래로 교체한다. **트림은 이 태스크에서 건드리지 않는다**(Task 2).

```python
def append_observation(path, ts, breadth, momentum, trend, sample, source, extra=None):
    """관측 한 건 append. 같은 분이 이미 있으면 아무것도 하지 않고 False.

    같은 분의 재실행이 값을 흔들면 이력이 런 재시도 여부에 의존하게 된다 —
    첫 값을 유지한다.

    `extra`는 OBS_EXTRA의 부분집합이다. 모르는 키는 **예외**다 — 조용히 버리면
    오타 하나로 그 기간의 열이 통째로 비고, 몇 달 뒤에나 발견된다.
    """
    extra = dict(extra or {})
    unknown = set(extra) - set(OBS_EXTRA)
    if unknown:
        raise ValueError(f"알 수 없는 관측 열: {sorted(unknown)}")

    existing = []
    if os.path.exists(path):
        with io.open(path, encoding='utf-8-sig') as f:
            existing = parse_observations(f.read())
        if any(r['ts'] == str(ts) for r in existing):
            return False

    row = {'ts': str(ts), 'breadth': float(breadth), 'momentum': float(momentum),
           'trend': trend, 'sample': int(sample), 'source': str(source)}
    row.update({col: extra.get(col) for col in OBS_EXTRA})
    existing.append(row)
    kept = trim_to_recent_dates(existing)   # 트림 제거는 Task 2의 단독 책임이다

    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(OBS_HEADER)
        for r in kept:
            w.writerow(format_row(r))
    os.replace(tmp, path)   # 중간에 죽어도 이력이 반토막 나지 않는다
    return True
```

- [ ] **Step 7: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_regime_observations.py -v`
Expected: PASS — 단 `test_append가_거래일_상한을_지킨다`는 여전히 통과한다(트림은 Task 2에서 뗀다)

- [ ] **Step 8: 커밋**

```bash
git add src/strategy/regime_observations.py tests/test_regime_observations.py
git commit -m "feat(regime): 관측 스키마를 6열에서 14열로 넓힌다"
```

---

## Task 2: 월별 분할과 트림 제거

**Files:**
- Modify: `src/strategy/regime_observations.py`
- Test: `tests/test_regime_observations.py`

**Interfaces:**
- Consumes: Task 1의 `OBS_HEADER`, `parse_observations`, `append_observation`
- Produces:
  - `OBS_ARCHIVE: str` = `'regime_observations.csv'` (파일명만. 읽기 전용 아카이브)
  - `month_path(now, data_dir: str = 'data') -> str` — `now`는 `datetime`
  - `load_all_observations(data_dir: str = 'data') -> list[dict]` — 아카이브 + 월별 전부, 시각 오름차순, `ts` 중복은 먼저 나온 것 유지
  - `OBS_PATH_REL`은 **이 태스크에서 지우지 않는다.** `trade_engine`·`trade_loop`이 아직 읽는다. 여기서 지우면 T3·T4 전까지 트리가 빨개지고, `trade_engine` 쪽은 `try/except` 안이라 **조용히** 실패한다 — 관측이 한 건도 안 쌓이는데 로그 한 줄로 끝난다. 삭제는 T4 Step 8이 한다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_regime_observations.py`의 `test_append가_거래일_상한을_지킨다`를 삭제하고 아래를 추가한다.

```python
import datetime as _dt

from src.strategy.regime_observations import (
    OBS_ARCHIVE, load_all_observations, month_path,
)


def test_월별_경로는_기존_규약을_따른다(tmp_path):
    # src/data/rank_snapshot.py::month_path와 같은 모양이어야 한다 — 새 규약을 지어내지 않는다.
    aug = month_path(_dt.datetime(2026, 8, 31, 15, 30), str(tmp_path))
    sep = month_path(_dt.datetime(2026, 9, 1, 9, 10), str(tmp_path))
    assert os.path.basename(aug) == 'regime_observations_2026-08.csv'
    assert os.path.basename(sep) == 'regime_observations_2026-09.csv'
    assert aug != sep, '월 경계에서 파일이 갈려야 한다'


def test_append는_더는_자르지_않는다(tmp_path):
    # 이게 60거래일 천장의 정체였다. 기다려도 표본이 늘지 않았다.
    p = str(tmp_path / 'obs.csv')
    made = []
    for month, last in ((6, 30), (7, 31), (8, 31)):
        for d in range(1, last + 1):
            if len(made) >= MAX_DISTINCT_DATES + 5:
                break
            made.append(f'2026-{month:02d}-{d:02d} 09:10')
    assert len(made) == MAX_DISTINCT_DATES + 5, '상한을 넘기지 못하면 이 테스트는 아무것도 검증하지 않는다'
    for ts in made:
        append_observation(p, ts, 50.0, 0.0, None, 100, 's')

    dates = sorted({r['ts'][:10] for r in parse_observations(_read(p))})
    assert len(dates) == MAX_DISTINCT_DATES + 5, '오래된 날짜가 남아 있어야 한다'
    assert made[0][:10] in dates, '가장 오래된 날짜가 사라지면 안 된다'


def test_트림_함수는_남아_있다():
    # 저장 창에서는 뗐지만 계산 창(직전 60거래일 분위수)에서는 여전히 쓴다.
    rows = [{'ts': f'2026-07-{d:02d} 09:10'} for d in range(1, 21)]
    assert len({r['ts'][:10] for r in trim_to_recent_dates(rows, max_dates=5)}) == 5


def test_아카이브와_월별을_시각순으로_이어붙인다(tmp_path):
    d = str(tmp_path)
    append_observation(os.path.join(d, OBS_ARCHIVE), '2026-07-31 09:10', 72.0, 2.69, 33.7, 100, 'top100_live')
    append_observation(month_path(_dt.datetime(2026, 8, 17), d), '2026-08-17 09:10', 61.0, 0.42, 44.9, 100, 'top100_live')
    append_observation(month_path(_dt.datetime(2026, 9, 1), d), '2026-09-01 09:10', 55.0, -0.10, 40.0, 100, 'top100_live')

    rows = load_all_observations(d)
    assert [r['ts'] for r in rows] == ['2026-07-31 09:10', '2026-08-17 09:10', '2026-09-01 09:10']


def test_중복_시각은_먼저_나온_것을_남긴다(tmp_path):
    # 아카이브와 월별 파일이 같은 분을 담을 수 있다(이행 구간). 두 번 세면 표본이 부풀고,
    # 값이 다르면 학습이 같은 시각에 두 정답을 본다.
    d = str(tmp_path)
    append_observation(os.path.join(d, OBS_ARCHIVE), '2026-08-14 15:30', 77.0, 1.35, None, 100, 'top100_live')
    append_observation(month_path(_dt.datetime(2026, 8, 14), d), '2026-08-14 15:30', 99.0, 9.99, None, 100, 'x')

    rows = load_all_observations(d)
    assert len(rows) == 1
    assert rows[0]['breadth'] == 77.0, '아카이브가 먼저다'


def test_빈_디렉터리는_빈_리스트다(tmp_path):
    assert load_all_observations(str(tmp_path)) == []
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_regime_observations.py -v`
Expected: FAIL — `ImportError: cannot import name 'OBS_ARCHIVE'`

- [ ] **Step 3: 월별 경로와 전체 로드를 추가한다**

`src/strategy/regime_observations.py`의 `OBS_PATH_REL` 정의는 **그대로 두고**, 그 아래에 아래를 넣는다. 파일 상단 import에 `import glob`을 더한다.

```python
# 읽기 전용 아카이브. 2026-08 월별 분할 이전에 쌓인 426행이 여기 있다.
# 새 쓰기는 전부 month_path()로 간다.
OBS_ARCHIVE = 'regime_observations.csv'

_MONTH_GLOB = 'regime_observations_[0-9][0-9][0-9][0-9]-[0-9][0-9].csv'


def month_path(now, data_dir: str = 'data') -> str:
    """월별 분할. rank_snapshot·sim_diag·post_archive와 같은 규약이다.

    한 파일이 무한정 커지는 것을 막는다. append가 매번 전체 재작성이고
    db-data가 10분마다 커밋을 받으므로, 단일 파일이면 1년차에 커밋당
    ~810KB짜리 blob이 하루 39개씩 쌓인다.
    """
    return os.path.join(data_dir, f"regime_observations_{now.strftime('%Y-%m')}.csv")


def load_all_observations(data_dir: str = 'data') -> list:
    """아카이브 + 월별 전부를 시각 오름차순 단일 리스트로.

    같은 `ts`가 두 파일에 있으면 **먼저 읽은 것**(아카이브 우선)을 남긴다.
    이행 구간에 아카이브와 그 달 파일이 같은 분을 담을 수 있는데, 두 번 세면
    표본이 부풀고 값이 다르면 같은 시각에 정답이 둘이 된다.
    """
    paths = [os.path.join(data_dir, OBS_ARCHIVE)]
    paths += sorted(glob.glob(os.path.join(data_dir, _MONTH_GLOB)))

    seen, rows = set(), []
    for p in paths:
        if not os.path.exists(p):
            continue
        with io.open(p, encoding='utf-8-sig') as f:
            for r in parse_observations(f.read()):
                if r['ts'] in seen:
                    continue
                seen.add(r['ts'])
                rows.append(r)
    rows.sort(key=lambda r: r['ts'])
    return rows
```

- [ ] **Step 4: 트림 호출을 뗀다**

`append_observation`에서 트림 두 줄을 걷어낸다. Task 1이 넣어둔 형태:

```python
    kept = trim_to_recent_dates(existing)   # 트림 제거는 Task 2의 단독 책임이다

    tmp = path + '.tmp'
    ...
        for r in kept:
```

이걸 아래로 바꾼다.

```python
    tmp = path + '.tmp'
    ...
        for r in existing:
```

`trim_to_recent_dates`와 `MAX_DISTINCT_DATES`는 **지우지 않는다** — 계산 창에서 쓴다. 다만 상수 주석을 아래로 바꾼다.

```python
# 계산 창의 기본 거래일 수. **저장 창이 아니다** — 2026-08까지는 append가 매번
# 이걸로 잘라서, 기다려도 표본이 60거래일에서 늘지 않았다. 지금은 판정기·라벨러가
# 분위수 창을 잡을 때만 쓴다.
MAX_DISTINCT_DATES = 60
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_regime_observations.py -v`
Expected: PASS

- [ ] **Step 6: 아직 아무것도 깨지지 않았는지 확인한다**

Run: `python -m pytest tests/test_regime_observations.py tests/test_trade_loop.py -q`
Expected: PASS. `OBS_PATH_REL`을 남겨뒀으므로 `trade_loop`은 그대로 돈다.

Run: `grep -rn "OBS_PATH_REL" --include=*.py . | grep -v __pycache__`
Expected: `regime_observations.py`(정의), `trade_engine.py`, `trade_loop.py` 세 곳. Task 3·4에서 걷어낸다.

- [ ] **Step 7: 커밋**

```bash
git add src/strategy/regime_observations.py tests/test_regime_observations.py
git commit -m "feat(regime): 60거래일 천장을 없애고 월별 파일로 쪼갠다"
```

---

## Task 3: 배포 매니페스트가 월별 파일명을 해석한다

**Files:**
- Modify: `scripts/trade_loop.py:266-281` (`regime_output_files`), `scripts/trade_loop.py:285-` (`_write_deploy_manifest`), 호출부 2곳(`:345`, `:436`)
- Test: `tests/test_trade_loop.py`

**Interfaces:**
- Consumes: Task 2의 `month_path`
- Produces: `regime_output_files(now) -> list[str]` — 인자 추가

**왜 이 태스크가 따로인가:** 여기서 빠뜨리면 달이 바뀐 첫 거래일에 새 파일이 db-data에 도달하지 못하고 그 달 이력이 통째로 유실된다. **조용하다** — 로그에 오류가 없다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_trade_loop.py` 끝에 추가한다.

```python
def test_배포_목록이_쓰기_경로와_같은_파일을_가리킨다():
    """쓰는 파일과 올리는 파일이 갈리면 그 달 이력이 통째로 유실된다. 조용하다."""
    import datetime as _dt
    import os
    from scripts.trade_loop import regime_output_files
    from src.strategy.regime_observations import month_path

    now = _dt.datetime(2026, 9, 1, 9, 10)
    assert os.path.basename(month_path(now)) in regime_output_files(now)


def test_월이_바뀌면_배포_대상도_바뀐다():
    import datetime as _dt
    from scripts.trade_loop import regime_output_files

    aug = set(regime_output_files(_dt.datetime(2026, 8, 31, 15, 30)))
    sep = set(regime_output_files(_dt.datetime(2026, 9, 1, 9, 10)))
    assert 'regime_observations_2026-08.csv' in aug
    assert 'regime_observations_2026-09.csv' in sep
    assert 'regime_observations_2026-08.csv' not in sep


def test_국면을_올리는데_시각이_없으면_시끄럽게_실패한다(tmp_path, monkeypatch):
    """시각 없이 기본값으로 넘어가면 월 경계에서 조용히 틀린 파일을 올린다."""
    import pytest
    from scripts import trade_loop

    monkeypatch.chdir(tmp_path)
    (tmp_path / 'data').mkdir()
    with pytest.raises(ValueError):
        trade_loop._write_deploy_manifest(None, log=lambda *a: None, include_regime=True)
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_trade_loop.py -k "배포_목록 or 월이_바뀌면 or 시각이_없으면" -v`
Expected: FAIL — `regime_output_files() takes 0 positional arguments but 1 was given`

- [ ] **Step 3: `regime_output_files`에 시각을 넣는다**

`scripts/trade_loop.py`의 `regime_output_files`를 아래로 교체한다.

```python
def regime_output_files(now) -> list[str]:
    """국면 갱신이 쓰는 파일들(data/ 기준 상대 이름).

    이 워크플로가 국면의 유일 writer가 됐으므로, 여기서 빠뜨리면 갱신한 국면이
    db-data에 영영 도달하지 못한다 — 그러면 두 워크플로가 모두 얼어붙은 국면을
    읽게 되고, 그건 실패가 아니라 '조용히 낡은 값으로 매매'다.

    관측 이력은 월별 파일이다. 파일명을 런타임에 해석해야 한다 — 배포 스텝이
    `[ -f data/$name ]`로 한 줄씩 존재를 검사하므로 와일드카드가 매칭되지 않는다.
    `now`는 **관측을 기록한 시각**이어야 한다(= trade_engine이 쓴 ctx.now_kst).
    """
    from src.strategy.registry import get_sim_registry
    from src.strategy.regime_observations import month_path

    # 게이트 파일도 함께 올린다. 이게 db-data에 도달하지 못하면 다음 런이 "아직
    # 안 갱신했다"로 읽어 격자당 3회로 되돌아간다 — 게이트를 만든 의미가 사라진다.
    # 아카이브(regime_observations.csv)는 올리지 않는다 — 읽기 전용이라 안 바뀐다.
    out = [os.path.basename(month_path(now)), 'regime_gate_state.json']
    for s in get_sim_registry(include_analyzers=True):
        if s['analyzer']:
            out += [s['state_file'], s['csv_file']]
    return out
```

- [ ] **Step 4: `_write_deploy_manifest`가 시각을 받아 넘긴다**

시그니처와 국면 분기를 아래로 바꾼다.

```python
def _write_deploy_manifest(sim_id: str | None, log=print,
                           now=None,
                           include_regime: bool = False,
                           include_money=None,
                           include_alerts: bool = False) -> None:
```

**가드는 `try:` 바깥에 둔다.** 함수 본문이 `except Exception as e: log(...)`로 끝나므로, 안에서 던지면 로그 한 줄로 삼켜지고 그 달 이력이 조용히 유실된다 — 막으려던 실패 모드가 그대로 재현된다.

docstring 바로 아래, `try:` **앞**에 넣는다.

```python
    if include_regime and now is None:
        # try 안에 두면 아래 except가 삼켜서 로그 한 줄로 끝난다. 그러면 월 경계에
        # 조용히 지난달 파일을 올리게 되고, 그게 이 가드가 막으려던 바로 그 실패다.
        raise ValueError('include_regime에는 기록 시각(now)이 필요하다')
    try:
```

그리고 `try:` 안의 국면 분기를 아래로 바꾼다.

```python
        if include_regime:
            names += regime_output_files(now)
```

- [ ] **Step 5: 호출부 두 곳에 시각을 넘긴다**

`scripts/trade_loop.py:345` 부근:

```python
        _write_deploy_manifest(None, ctx.log, now=ctx.now_kst,
                               include_alerts=alerts.state_was_written())
```

`scripts/trade_loop.py:436` 부근:

```python
        _write_deploy_manifest(traded_sim_id, ctx.log, now=ctx.now_kst,
                               include_regime=regime_refreshed,
                               include_money=money_at,
                               include_alerts=alerts_written)
```

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_trade_loop.py -v`
Expected: PASS — 기존 테스트 포함 전부

- [ ] **Step 7: 커밋**

```bash
git add scripts/trade_loop.py tests/test_trade_loop.py
git commit -m "feat(regime): 배포 목록이 월별 관측 파일명을 런타임에 해석한다"
```

---

## Task 4: 수집부 — 헤더로 열을 찾고 신규 지표를 채운다

**Files:**
- Modify: `src/pipeline/workers/trade_engine.py` — `_fetch_top100_breadth`(`:669-721`), `_append_regime_observation`(`:723-742`), `_run_libero` 내 `live_breadth` 참조부(`:296-331`)
- Test: `tests/test_regime_metrics.py` (신규)

**Interfaces:**
- Consumes: Task 1의 `append_observation(..., extra=)`, Task 2의 `month_path`
- Produces:
  - `resolve_market_columns(header_texts: list[str]) -> dict | None` — `{'price':2,'rate':4,'cap':6,'volume':9}` 또는 실패 시 `None`
  - `market_extras(rates, caps, prices, volumes) -> dict` — `OBS_EXTRA`의 부분집합. 재료가 없으면 그 열은 넣지 않는다
  - `_fetch_top100_breadth()` 반환형이 **튜플에서 dict로** 바뀐다: `{'breadth','momentum','sample','codes','extra'}`

**실측 근거 (2026-08-17):** 네이버 `sise_market_sum` 응답의 `thead th` 13개 =
`['N','종목명','현재가','전일비','등락률','액면가','시가총액','상장주식수','외국인비율','거래량','PER','ROE','토론']`,
행의 `td`도 13개. 인덱스가 정렬되어 `등락률`이 현행 `cols[4]`와 일치한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_regime_metrics.py`를 만든다.

```python
# -*- coding: utf-8 -*-
"""top100 응답에서 파생하는 국면 지표 — 추가 요청 0건.

지금까지 cols[4](등락률)만 쓰고 현재가·시가총액·거래량을 버렸다. 등락률 벡터
100개도 상승비율과 median 둘로 뭉개져, "전부 조금씩 올랐다"와 "몇 개가 급등하고
나머지는 빠졌다"가 같은 행으로 기록됐다.
"""
from src.pipeline.workers.trade_engine import market_extras, resolve_market_columns

REAL_HEADER = ['N', '종목명', '현재가', '전일비', '등락률', '액면가', '시가총액',
               '상장주식수', '외국인비율', '거래량', 'PER', 'ROE', '토론']


def test_실제_헤더에서_열_위치를_찾는다():
    # 2026-08-17 실측 응답. 등락률이 현행 고정 인덱스 4와 일치한다.
    cols = resolve_market_columns(REAL_HEADER)
    assert cols == {'price': 2, 'rate': 4, 'cap': 6, 'volume': 9}


def test_열이_밀려도_따라간다():
    shifted = ['N', '종목명', '신규열', '현재가', '전일비', '등락률', '액면가',
               '시가총액', '상장주식수', '외국인비율', '거래량']
    assert resolve_market_columns(shifted)['rate'] == 5


def test_헤더를_못_읽으면_None이다():
    assert resolve_market_columns(['N', '종목명', '???']) is None


def test_시총가중_상승비율은_동일가중과_다르다():
    # 대형주 하나만 오르고 소형주 셋이 빠진 날. 동일가중 25%, 시총가중은 훨씬 높다.
    out = market_extras(rates=[1.0, -1.0, -1.0, -1.0],
                        caps=[900.0, 10.0, 10.0, 10.0],
                        prices=[100.0] * 4, volumes=[1000.0] * 4)
    assert out['breadth_cap'] == 96.8
    assert out['up'] == 1
    assert out['down'] == 3


def test_분위수는_보간하지_않는다():
    out = market_extras(rates=[float(i) for i in range(1, 101)],
                        caps=[1.0] * 100, prices=[1.0] * 100, volumes=[1.0] * 100)
    # floor(q * (n-1))로 뽑는다 — 표본이 85~100으로 흔들려도 정의가 안 변한다.
    assert out['p10'] == 10.0
    assert out['p25'] == 25.0
    assert out['p75'] == 75.0
    assert out['p90'] == 90.0


def test_turnover는_억원_정수다():
    out = market_extras(rates=[1.0, 1.0], caps=[1.0, 1.0],
                        prices=[274500.0, 1645000.0], volumes=[21668266.0, 1000000.0])
    # (274500*21668266 + 1645000*1000000) / 1e8
    assert out['turnover'] == int((274500 * 21668266 + 1645000 * 1000000) / 1e8)


def test_재료가_없으면_그_열을_아예_넣지_않는다():
    # 헤더 해석 실패 시 등락률만 남는다. 0으로 채우면 '측정 못 함'이 값이 된다.
    out = market_extras(rates=[1.0, -1.0], caps=None, prices=None, volumes=None)
    assert 'breadth_cap' not in out
    assert 'turnover' not in out
    assert out['up'] == 1 and out['down'] == 1
    assert out['p10'] == -1.0


def test_시총_합이_0이면_breadth_cap을_넣지_않는다():
    out = market_extras(rates=[1.0, -1.0], caps=[0.0, 0.0],
                        prices=[1.0, 1.0], volumes=[1.0, 1.0])
    assert 'breadth_cap' not in out
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_regime_metrics.py -v`
Expected: FAIL — `ImportError: cannot import name 'market_extras'`

- [ ] **Step 3: 모듈 수준 헬퍼 두 개를 추가한다**

`src/pipeline/workers/trade_engine.py`의 `_adx` 정의 **아래**(클래스 `TradeEngineWorker` 정의 위)에 넣는다.

```python
# 네이버 시총 페이지의 열 라벨. 인덱스가 아니라 이 텍스트로 위치를 찾는다 —
# 고정 인덱스를 5개로 늘리면 네이버가 열 하나를 끼워넣는 순간 5개가 동시에
# 조용히 틀린다. 2026-08-17 실측: th 13개, td 13개, 인덱스 정렬됨.
_MARKET_COL_LABELS = {'price': '현재가', 'rate': '등락률',
                      'cap': '시가총액', 'volume': '거래량'}


def resolve_market_columns(header_texts):
    """헤더 텍스트 → td 인덱스. 하나라도 못 찾으면 None(호출부가 현행 폴백)."""
    try:
        return {k: header_texts.index(v) for k, v in _MARKET_COL_LABELS.items()}
    except ValueError:
        return None


def _quantile(sorted_vals, q):
    """정렬된 값에서 분위수. 선형보간 없이 floor(q·(n-1)) 인덱스.

    보간하면 표본이 85~100으로 흔들릴 때 정의가 미묘하게 따라 움직인다.
    """
    return sorted_vals[int(q * (len(sorted_vals) - 1))]


def market_extras(rates, caps=None, prices=None, volumes=None):
    """top100 응답 → OBS_EXTRA 열들. **재료가 없는 열은 넣지 않는다**(0으로 안 채운다).

    `caps`/`prices`/`volumes`는 헤더 해석에 실패하면 None이다. 그때도 등락률에서
    나오는 열(분위수·상승하락수)은 그대로 채운다.
    """
    out = {}
    if not rates:
        return out

    out['up'] = sum(1 for r in rates if r > 0)
    out['down'] = sum(1 for r in rates if r < 0)

    ordered = sorted(rates)
    for name, q in (('p10', 0.10), ('p25', 0.25), ('p75', 0.75), ('p90', 0.90)):
        out[name] = round(_quantile(ordered, q), 2)

    if caps and len(caps) == len(rates):
        total = sum(caps)
        if total > 0:
            up_cap = sum(c for c, r in zip(caps, rates) if r > 0)
            out['breadth_cap'] = round(up_cap / total * 100, 1)

    if prices and volumes and len(prices) == len(rates) == len(volumes):
        # 정확한 거래대금이 아니다 — 현재가 × 누적거래량은 평균단가를 쓰지 않는다.
        # 절대 수준이 아니라 시각 간 상대 변화를 보는 용도다.
        out['turnover'] = int(sum(p * v for p, v in zip(prices, volumes)) / 1e8)

    return out
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_regime_metrics.py -v`
Expected: PASS

- [ ] **Step 5: 수집부가 새 열을 모으게 한다**

`_fetch_top100_breadth`의 본문을 아래로 교체한다. docstring의 반환 설명도 함께 바꾼다.

```python
    def _fetch_top100_breadth(self):
        """네이버 시총 페이지에서 KOSPI top100 장중 등락률 → 실측 국면 지표.

        fetch_kospi_top100.py와 동일 소스(sise_market_sum). 표본이 80 미만이면
        부분 실패로 보고 None (왜곡된 실측으로 채점 오염 방지).

        반환: {'breadth','momentum','sample','codes','extra'} 또는 None.
        `extra`는 OBS_EXTRA의 부분집합이다 — 헤더 해석에 실패하면 등락률에서
        나오는 열만 담긴다.
        """
        import requests
        from bs4 import BeautifulSoup

        naver_hdrs = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://finance.naver.com/',
        }
        codes, rates = [], []
        caps, prices, volumes = [], [], []
        seen: set = set()

        def _num(cols, idx):
            if idx is None or idx >= len(cols):
                return None
            txt = cols[idx].get_text(strip=True).replace(',', '').replace('%', '')
            try:
                return float(txt)
            except ValueError:
                return None

        for page in range(1, 5):
            url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page={page}"
            res = requests.get(url, headers=naver_hdrs, timeout=10)
            soup = BeautifulSoup(res.content.decode('euc-kr', 'replace'), 'html.parser')
            table = soup.select_one('table.type_2')
            if not table:
                break
            # 헤더 해석 실패 시 등락률만 현행 고정 인덱스로 읽는다 — 기존 동작은
            # 어떤 경우에도 나빠지지 않고, 신규 열만 비게 된다.
            idx = resolve_market_columns(
                [th.get_text(strip=True) for th in table.select('thead th')]
            ) or {'rate': 4, 'price': None, 'cap': None, 'volume': None}
            for row in table.select('tr'):
                cols = row.select('td')
                if len(cols) < 5:
                    continue
                name_tag = cols[1].select_one('a')
                if not name_tag:
                    continue
                code = name_tag['href'].split('code=')[-1]
                if not code.isdigit() or code in seen:
                    continue
                rate = _num(cols, idx['rate'])
                if rate is None:
                    continue
                seen.add(code)
                codes.append(code)
                rates.append(rate)
                caps.append(_num(cols, idx['cap']))
                prices.append(_num(cols, idx['price']))
                volumes.append(_num(cols, idx['volume']))
                if len(codes) >= 100:
                    break
            if len(codes) >= 100:
                break
        if len(codes) < 80:
            return None
        bm = self._breadth_momentum(rates)
        if bm is None:
            # 표본은 찼는데 아직 안 움직였다(개장 직후). 여기서 언팩하면 터지고,
            # 0으로 적으면 08-06~08-13처럼 리베로 예측이 통째로 0이 된다.
            return None

        def _clean(xs):
            return xs if all(x is not None for x in xs) else None

        return {
            'breadth': bm[0], 'momentum': bm[1], 'sample': len(codes), 'codes': codes,
            'extra': market_extras(rates, _clean(caps), _clean(prices), _clean(volumes)),
        }
```

- [ ] **Step 6: `live_breadth` 참조부를 dict로 바꾼다**

`_run_libero`에서 튜플 인덱싱을 키 접근으로 바꾼다. 바뀌는 곳은 5군데다.

```python
            'trend': self._top100_trend_from_csv(),  # None이면 Sim0가 버즈 ADX로 폴백(candidates=[]라 0.0)
            'sample': live_breadth['sample'],
        } if live_breadth else None
```

```python
            'breadth': live_breadth['breadth'],
            'momentum': live_breadth['momentum'],
```

```python
                actual_eod = live_breadth['breadth'] if live_breadth else self._get_actual_breadth_from_csv()
```

```python
            elif action == 'nowcast' and live_breadth:
                codes = live_breadth['codes']
                sim.update_nowcast(
                    live_breadth['breadth'], now_kst=now_kst,
                    backfill=lambda hhmm: self._backfill_breadth_kis(hhmm, codes))
```

- [ ] **Step 7: append 배선을 월별 경로와 `extra`로 바꾼다**

`_append_regime_observation`의 본문을 아래로 교체한다.

```python
        if not live_breadth:
            return
        try:
            from src.strategy.regime_observations import append_observation, month_path
            append_observation(
                month_path(now_kst),
                now_kst.strftime('%Y-%m-%d %H:%M'),
                live_breadth['breadth'], live_breadth['momentum'],
                self._top100_trend_from_csv(),
                live_breadth['sample'], 'top100_live',
                extra=live_breadth['extra'])
        except Exception as e:
            self.log_error(f"국면 관측 이력 기록 실패: {e}")
```

- [ ] **Step 8: `OBS_PATH_REL`을 지운다 — 마지막 참조가 사라진 지금이다**

Run: `grep -rn "OBS_PATH_REL" --include=*.py . | grep -v __pycache__`
Expected: `src/strategy/regime_observations.py`의 정의 한 줄만 남는다(T3가 trade_loop을, Step 7이 trade_engine을 `month_path`로 옮겼다).

그 정의를 삭제한다. 다른 곳이 아직 나오면 **지우지 말고** 그 참조부터 `month_path`로 옮긴다 — 상수를 먼저 지우면 `trade_engine`의 `try/except`가 ImportError를 삼켜 관측이 조용히 0건이 된다.

Run: `grep -rn "OBS_PATH_REL" --include=*.py . | grep -v __pycache__`
Expected: 아무것도 안 나온다.

- [ ] **Step 9: 전체 테스트를 돌린다**

Run: `python -m pytest tests/test_regime_metrics.py tests/test_regime_observations.py tests/test_trade_loop.py tests/test_sim0_regime.py tests/test_sim0_nowcast.py tests/test_breadth_not_yet_trading.py -v`
Expected: PASS

- [ ] **Step 10: 실제 응답으로 한 번 확인한다**

Run:
```bash
python -c "
import sys; sys.path.insert(0,'.')
from src.pipeline.workers.trade_engine import resolve_market_columns
import requests
from bs4 import BeautifulSoup
h={'User-Agent':'Mozilla/5.0','Referer':'https://finance.naver.com/'}
r=requests.get('https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page=1',headers=h,timeout=15)
t=BeautifulSoup(r.content.decode('euc-kr','replace'),'html.parser').select_one('table.type_2')
print(resolve_market_columns([x.get_text(strip=True) for x in t.select('thead th')]))
"
```
Expected: `{'price': 2, 'rate': 4, 'cap': 6, 'volume': 9}`. 다른 값이 나오면 네이버가 열을 바꾼 것이니 **폴백이 도는지**를 확인하고 넘어간다(신규 열만 비면 정상).

- [ ] **Step 11: 커밋**

```bash
git add src/pipeline/workers/trade_engine.py tests/test_regime_metrics.py
git commit -m "feat(regime): 버리던 현재가·시총·거래량과 등락률 분포를 남긴다"
```

---

## Task 5: 충분성 리포트

**Files:**
- Create: `scripts/regime_data_status.py`
- Test: `tests/test_regime_data_status.py`

**Interfaces:**
- Consumes: Task 2의 `load_all_observations`
- Produces:
  - `pair_observations(rows, horizon_min=30, tol_min=5) -> list[tuple[dict, dict]]` — `(t, t+지평)` 쌍. 같은 거래일만
  - `naive_mae(pairs) -> float | None` — `mean(|breadth_j - breadth_i|)`
  - `column_coverage(rows) -> dict[str, float]` — 열별 **채움**률(0.0~1.0)
  - `main() -> int`

**왜 나이브 MAE가 핵심인가:** 표본만 세는 리포트는 문제가 얼마나 어려운지를 말해주지 않는다. 기준선 MAE가 이미 작으면 이길 여지가 없다는 뜻이고, 그건 표본을 더 쌓아도 변하지 않는다 — 몇 달 쌓기 전에 알아야 할 답이다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_regime_data_status.py`를 만든다.

```python
# -*- coding: utf-8 -*-
"""충분성 리포트 — "언제 학습을 시작하나"에 답한다."""
from scripts.regime_data_status import column_coverage, naive_mae, pair_observations


def _row(ts, breadth, **kw):
    r = {'ts': ts, 'breadth': breadth, 'momentum': 0.0, 'trend': None,
         'sample': 100, 'source': 'top100_live'}
    for col in ('breadth_cap', 'p10', 'p25', 'p75', 'p90', 'up', 'down', 'turnover'):
        r[col] = kw.get(col)
    return r


def test_30분_뒤_관측과_짝짓는다():
    rows = [_row('2026-08-17 09:00', 50.0), _row('2026-08-17 09:30', 60.0)]
    pairs = pair_observations(rows)
    assert len(pairs) == 1
    assert pairs[0][1]['breadth'] == 60.0


def test_관측_격자가_어긋나도_허용오차_안이면_짝이_된다():
    # 실제 격자는 09:01, 09:13, 09:25, 09:37...로 11~12분 간격이다. 정확히 +30분은 없다.
    rows = [_row('2026-08-17 09:01', 50.0), _row('2026-08-17 09:33', 60.0)]
    assert len(pair_observations(rows)) == 1


def test_허용오차_밖이면_짝이_아니다():
    rows = [_row('2026-08-17 09:00', 50.0), _row('2026-08-17 09:50', 60.0)]
    assert pair_observations(rows) == []


def test_날짜를_넘어_짝짓지_않는다():
    # 15:20의 30분 뒤는 장이 끝난 뒤다. 다음날 09:00과 이으면 오버나이트가 장중으로 둔갑한다.
    rows = [_row('2026-08-17 15:20', 50.0), _row('2026-08-18 09:00', 90.0)]
    assert pair_observations(rows) == []


def test_장_마감_직전_관측은_라벨이_없다():
    rows = [_row('2026-08-17 15:00', 50.0), _row('2026-08-17 15:30', 55.0)]
    assert len(pair_observations(rows)) == 1, '15:00은 짝이 있고 15:30은 없다'


def test_나이브_기준선은_현재값_유지다():
    rows = [_row('2026-08-17 09:00', 50.0), _row('2026-08-17 09:30', 56.0),
            _row('2026-08-17 10:00', 54.0)]
    # |56-50| = 6, |54-56| = 2 → 4.0
    assert naive_mae(pair_observations(rows)) == 4.0


def test_짝이_없으면_MAE는_None이다():
    assert naive_mae([]) is None


def test_열_채움률은_결측을_센다():
    rows = [_row('2026-08-17 09:00', 50.0, turnover=100),
            _row('2026-08-17 09:30', 60.0)]
    cov = column_coverage(rows)
    assert cov['breadth'] == 1.0
    assert cov['turnover'] == 0.5
    assert cov['trend'] == 0.0
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_regime_data_status.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.regime_data_status'`

- [ ] **Step 3: 리포트를 만든다**

`scripts/regime_data_status.py`를 만든다.

```python
# -*- coding: utf-8 -*-
"""국면 관측 충분성 리포트 — "언제 학습을 시작하나"에 답한다.

읽기 전용이다. 아무 파일도 쓰지 않는다.

목표 모델은 30분 앞 장중 breadth 포캐스트다. 승격 기준은
docs/superpowers/specs/2026-08-17-regime-observation-accumulation-design.md §7.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategy.regime_observations import OBS_HEADER  # noqa: E402
from src.strategy.regime_observations import load_all_observations  # noqa: E402

HORIZON_MIN = 30
TOL_MIN = 5

# §7의 하한: 학습 40일 + 검증 5일 × 4회.
MIN_TRADING_DAYS = 60

_BUCKETS = (('09~10시', 9, 10), ('10~12시', 10, 12), ('12~15시', 12, 24))


def _ts(row):
    return datetime.strptime(row['ts'], '%Y-%m-%d %H:%M')


def pair_observations(rows, horizon_min=HORIZON_MIN, tol_min=TOL_MIN):
    """(t, t+지평) 쌍. 같은 거래일만, 지평에 가장 가까운 관측 하나.

    실제 격자는 09:01, 09:13, 09:25처럼 11~12분 간격이라 정확히 +30분은 없다.
    허용오차 안에서 가장 가까운 것을 고른다.

    날짜를 넘지 않는다 — 15:20의 30분 뒤는 장이 끝난 뒤이고, 다음날 09:00과
    이으면 오버나이트 수익이 장중 신호로 둔갑한다.
    """
    ordered = sorted(rows, key=lambda r: r['ts'])
    stamps = [_ts(r) for r in ordered]
    pairs = []
    for i, base in enumerate(stamps):
        best, best_gap = None, None
        for j in range(i + 1, len(stamps)):
            if ordered[j]['ts'][:10] != ordered[i]['ts'][:10]:
                break
            delta = (stamps[j] - base).total_seconds() / 60.0
            if delta > horizon_min + tol_min:
                break
            gap = abs(delta - horizon_min)
            if gap <= tol_min and (best_gap is None or gap < best_gap):
                best, best_gap = j, gap
        if best is not None:
            pairs.append((ordered[i], ordered[best]))
    return pairs


def naive_mae(pairs):
    """기준선 ①: 30분 뒤 breadth ≈ 지금 breadth."""
    if not pairs:
        return None
    errs = [abs(b['breadth'] - a['breadth']) for a, b in pairs]
    return round(sum(errs) / len(errs), 3)


def column_coverage(rows):
    """열별 채움률. 결측을 0으로 세지 않기 위해 명시적으로 센다."""
    if not rows:
        return {}
    keys = ['ts'] + [c for c in OBS_HEADER if c != 'ts_kst']
    out = {}
    for key in keys:
        filled = sum(1 for r in rows if r.get(key) is not None)
        out[key] = round(filled / len(rows), 3)
    return out


def _bucket(row):
    hour = int(row['ts'][11:13])
    for label, lo, hi in _BUCKETS:
        if lo <= hour < hi:
            return label
    return None


def main():
    rows = load_all_observations('data')
    if not rows:
        print('관측 이력이 없다. data/regime_observations*.csv 를 확인하라.')
        return 1

    dates = sorted({r['ts'][:10] for r in rows})
    print('=' * 60)
    print(f"거래일 {len(dates)}일 / {len(rows)}행   {dates[0]} ~ {dates[-1]}")
    print(f"§7 하한 {MIN_TRADING_DAYS}거래일까지 남은 일수: {max(0, MIN_TRADING_DAYS - len(dates))}")

    print('-' * 60)
    print('열별 채움률')
    for key, ratio in column_coverage(rows).items():
        bar = '#' * int(ratio * 20)
        print(f"  {key:<12} {ratio * 100:5.1f}%  {bar}")

    pairs = pair_observations(rows)
    print('-' * 60)
    print(f"유효 (관측, 라벨) 쌍: {len(pairs)}   (지평 {HORIZON_MIN}분, 허용오차 ±{TOL_MIN}분)")
    print('  전체 행에서 이만큼만 학습에 쓸 수 있다 — 장 마감 직전 관측과 결측 슬롯이 빠진다.')

    mae = naive_mae(pairs)
    print('-' * 60)
    if mae is None:
        print('나이브 기준선 MAE: 측정 불가 (쌍이 없다)')
    else:
        print(f"나이브 기준선 MAE (현재값 유지): {mae:.3f}p")
        for label, _, _ in _BUCKETS:
            sub = [(a, b) for a, b in pairs if _bucket(a) == label]
            sub_mae = naive_mae(sub)
            got = '측정 불가' if sub_mae is None else f"{sub_mae:6.3f}p"
            print(f"    {label}  n={len(sub):<5} {got}")
        print('  모델은 이 값을 이겨야 의미가 있다. 이미 작으면 이길 여지가 없다는 뜻이고,')
        print('  그건 표본을 더 쌓아도 변하지 않는다.')
    print('=' * 60)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_regime_data_status.py -v`
Expected: PASS

- [ ] **Step 5: 실제 데이터로 돌린다**

먼저 db-data의 아카이브를 받아 둔다.

```bash
git fetch origin db-data:db-data 2>/dev/null || true
git show db-data:data/regime_observations.csv > data/regime_observations.csv
python scripts/regime_data_status.py
```

Expected: 거래일 11일 / 426행, `2026-07-31 ~ 2026-08-14`. `trend` 채움률 ~54%, 신규 8열 0%. 나이브 기준선 MAE가 숫자로 찍힌다.

**이 숫자를 결과 보고에 그대로 옮긴다.** 몇 달 쌓기 전에 알아야 할 답이 여기 있다.

- [ ] **Step 6: 커밋**

```bash
git add scripts/regime_data_status.py tests/test_regime_data_status.py
git commit -m "feat(regime): 충분성 리포트 — 유효 쌍 수와 나이브 기준선 MAE"
```

---

## 마무리

- [ ] **전체 테스트**

Run: `python -m pytest tests/ -q`
Expected: 전부 통과. 실패가 있으면 이 계획이 건드린 파일과 관련 있는지 확인한다.

- [ ] **PR 올리기**

```bash
git push -u origin feat/regime-accumulation
gh pr create --title "feat(regime): 관측 축적 구조 — 60거래일 천장 제거와 14열 스키마" --body-file <파일>
```

PR 본문에 Step 5에서 얻은 **실제 나이브 기준선 MAE**를 적는다.

- [ ] **배포 후 확인 (머지 다음 거래일)**

1. db-data에 `data/regime_observations_2026-08.csv`가 생겼는가
2. 그 파일의 새 행에 신규 8열이 채워졌는가 (`turnover`가 0이 아닌지)
3. 기존 `data/regime_observations.csv`가 그대로인가 (건드리면 안 된다)
4. `regime_gate_state.json`이 계속 갱신되는가 (배포 목록에서 빠뜨리지 않았는지)

---

## Self-Review 결과

**스펙 커버리지**

| 스펙 절 | 태스크 |
|---|---|
| §2 스키마 14열 | Task 1 |
| §2 열 위치 헤더 해석 | Task 4 Step 3 |
| §3 트림 제거·월별 분할 | Task 2 |
| §4 경로 계약 (`month_path`, `regime_output_files(now)`) | Task 2, Task 3 |
| §5 결측 규약 | Task 1 (`_opt`, 빈 칸 왕복 테스트) |
| §6 충분성 리포트 | Task 5 |
| §7 채점 기준 | 문서 전용 — 구현 없음(의도) |
| §8 테스트 8종 | Task 1·2·3에 분산 |
| §11 실패 모드 (월 경계) | Task 3 Step 1 |

**남는 위험**

- Task 4 Step 5는 `_fetch_top100_breadth`의 반환형을 튜플에서 dict로 바꾼다. `live_breadth`를 인덱스로 읽는 곳이 5군데이며 Step 6에 전부 나열했다. 하나라도 놓치면 `TypeError`로 **시끄럽게** 죽으므로 조용한 실패는 아니다.
- `turnover`가 현재가×거래량 근사라는 사실은 스펙 §2와 코드 주석 두 곳에만 있다. 나중에 이 열을 절대 수준으로 해석하면 틀린다.
