# 휴장일 게이트 재설계 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 휴장일에 스크래퍼가 돌고 텔레그램이 발송되는 문제를, KIS 개장일 달력 캐시 + fail-closed 판정으로 고친다.

**Architecture:** `chk-holiday`(TR `CTCA0903R`)가 반환하는 약 3개월치 달력을 `data/market_calendar.json`에 통째로 저장한다. 07시 `token_refresh.yml`이 토큰 발급 직후 달력을 갱신하고 db-data에 push한다. 스크래퍼는 달력에서 오늘 키를 찾아 판정하고, 없으면 직접 재조회하며, 그것도 실패하면 `None`(판정 불가)을 반환해 파이프라인을 중단하고 경고를 보낸다.

**Tech Stack:** Python 3.10, requests, pytest, GitHub Actions

**설계 문서:** `docs/superpowers/specs/2026-07-17-market-holiday-gate-design.md`

## Global Constraints

- 개장 판정 소스는 **KIS `chk-holiday` 하나**다. **휴장 판정 경로**(`src/pipeline/context.py`)와
  스크래퍼 의존성(`scripts/requirements-scraper.txt`)에서 `holidays` 패키지를 제거한다.
  **저장소 전체 제거가 아니다** — `src/analyzer_5days.py`의 `get_recent_working_days()`도
  `holidays.KR()`을 쓰고 같은 결함(2026-07-17을 영업일로 계산)을 갖지만, 그 모듈은
  스크래퍼 런타임 import 체인에 없고(import 그래프 추적으로 확인) `analyze_cumulative()`는
  파이프라인 어디서도 호출되지 않는다. 이번 스코프 밖이다 (아래 "범위 밖" 참조).
- 개장 판정에는 **`opnd_yn`(개장일여부)만** 쓴다. `tr_day_yn`·`bzdy_yn`·`bzdy_tp_cd`는 쓰지 않는다 (`bzdy_tp_cd`는 응답 스펙에 없는 필드다).
- `is_trading_day()`는 **3값**을 반환한다: `True`(개장) / `False`(휴장) / `None`(판정 불가). **`None`은 개장이 아니다.**
- 실거래 게이트(`is_market_hours`, `is_after_market_close`)는 판정 불가 시 **닫히는**(False) 방향이어야 하고, 반환 타입은 `bool`로 좁힌다.
- `chk-holiday` 실전 도메인: `https://openapi.koreainvestment.com:9443` (모의투자 미지원).
- 작업 브랜치: `fix/market-holiday-gate` (이미 생성됨, 설계 문서 커밋 완료).
- 모든 로그·주석·커밋 메시지는 한국어로 쓴다 (기존 코드 스타일).

---

### Task 1: 달력 순수 함수 (`parse_calendar`, `lookup`)

API·파일 I/O 없이 검증 가능한 판정 로직부터 만든다.

**Files:**
- Create: `src/market_calendar.py`
- Test: `tests/test_market_calendar.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `parse_calendar(api_response: dict) -> dict[str, str]` — chk-holiday 응답 → `{bass_dt: opnd_yn}` 맵
  - `lookup(days: dict, yyyymmdd: str) -> bool | None` — `"Y"`→`True`, `"N"`→`False`, 키 없음→`None`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_market_calendar.py` 생성:

```python
"""KIS 개장일 달력 판정 테스트."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.market_calendar import parse_calendar, lookup


def test_parse_calendar_extracts_opnd_yn():
    """chk-holiday 응답에서 개장일여부(opnd_yn)만 뽑는다."""
    response = {
        'rt_cd': '0',
        'output': [
            {'bass_dt': '20260717', 'wday_dvsn_cd': '06', 'bzdy_yn': 'N',
             'tr_day_yn': 'N', 'opnd_yn': 'N', 'setl_day_yn': 'N'},
            {'bass_dt': '20260720', 'wday_dvsn_cd': '02', 'bzdy_yn': 'Y',
             'tr_day_yn': 'Y', 'opnd_yn': 'Y', 'setl_day_yn': 'Y'},
        ],
    }
    assert parse_calendar(response) == {'20260717': 'N', '20260720': 'Y'}


def test_parse_calendar_ignores_tr_day_yn():
    """개장 판정은 opnd_yn만 본다. tr_day_yn이 달라도 결과는 opnd_yn을 따른다."""
    response = {
        'rt_cd': '0',
        'output': [
            {'bass_dt': '20260717', 'bzdy_yn': 'Y', 'tr_day_yn': 'Y',
             'opnd_yn': 'N', 'setl_day_yn': 'Y'},
        ],
    }
    assert parse_calendar(response) == {'20260717': 'N'}


def test_parse_calendar_empty_output():
    assert parse_calendar({'rt_cd': '0', 'output': []}) == {}


def test_parse_calendar_skips_incomplete_rows():
    """필드가 빠진 행은 버린다 — 가짜 판정을 만들지 않는다."""
    response = {
        'output': [
            {'bass_dt': '20260717'},                  # opnd_yn 없음
            {'opnd_yn': 'Y'},                          # bass_dt 없음
            {'bass_dt': '20260720', 'opnd_yn': 'Y'},   # 정상
        ],
    }
    assert parse_calendar(response) == {'20260720': 'Y'}


def test_lookup_open_day():
    assert lookup({'20260720': 'Y'}, '20260720') is True


def test_lookup_closed_day():
    assert lookup({'20260717': 'N'}, '20260717') is False


def test_lookup_missing_key_is_none():
    """달력에 없는 날은 판정 불가(None)다. False가 아니다."""
    assert lookup({'20260717': 'N'}, '20261231') is None


def test_lookup_empty_calendar_is_none():
    assert lookup({}, '20260717') is None
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_market_calendar.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.market_calendar'`

- [ ] **Step 3: 최소 구현을 쓴다**

`src/market_calendar.py` 생성:

```python
"""KIS 국내휴장일조회(chk-holiday) 기반 개장일 달력.

chk-holiday(TR CTCA0903R)는 BASS_DT 하루가 아니라 약 3개월치 달력을 한 번에
반환한다. 응답을 통째로 저장해두면 재조회가 거의 필요 없고, 07시 갱신 런이
하루 실패해도 이전 저장분에 오늘이 들어있다.

개장 판정에는 opnd_yn(개장일여부)만 쓴다. tr_day_yn(거래일여부)·bzdy_yn(영업일여부)은
금융기관 업무일 기준이라 주식시장 개장일과 다를 수 있다.
"""


def parse_calendar(api_response: dict) -> dict:
    """chk-holiday 응답에서 {bass_dt: opnd_yn} 맵을 뽑는다.

    두 필드 중 하나라도 비면 그 행은 버린다 (가짜 판정 금지).
    """
    days = {}
    for row in api_response.get('output', []):
        bass_dt = row.get('bass_dt', '')
        opnd_yn = row.get('opnd_yn', '')
        if bass_dt and opnd_yn:
            days[bass_dt] = opnd_yn
    return days


def lookup(days: dict, yyyymmdd: str):
    """개장 여부. True=개장, False=휴장, None=판정 불가(달력에 없음)."""
    value = days.get(yyyymmdd)
    if value == 'Y':
        return True
    if value == 'N':
        return False
    return None
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_market_calendar.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/market_calendar.py tests/test_market_calendar.py
git commit -m "feat(holiday): KIS 개장일 달력 순수 판정 함수 추가

parse_calendar는 chk-holiday 응답에서 opnd_yn만 뽑는다.
lookup은 3값(True/False/None)을 돌려준다 — 달력에 없는 날은
판정 불가이지 휴장이 아니다.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: 달력 I/O (`fetch_calendar`, `load/save`, `refresh_calendar`)

API 호출과 파일 저장을 붙인다.

**Files:**
- Modify: `src/market_calendar.py` (Task 1에서 만든 파일에 추가)
- Test: `tests/test_market_calendar.py` (Task 1 파일에 추가)

**Interfaces:**
- Consumes: `parse_calendar(api_response: dict) -> dict[str, str]` (Task 1)
- Produces:
  - `fetch_calendar(access_token: str, app_key: str, app_secret: str, base_date: str) -> dict[str, str]`
    — **실패 시 예외.** `rt_cd != '0'`과 빈 달력은 `RuntimeError`, HTTP·타임아웃·연결
    오류는 `requests` 예외(`HTTPError` 등), 본문이 JSON이 아니면 `JSONDecodeError`가
    그대로 전파된다. 호출부는 예외 **클래스를 좁혀 잡지 말 것** — `except Exception`으로
    받아 판정 불가(`None`)로 귀결시킨다 (Task 3이 그렇게 한다).
  - `load_calendar(path: str = CALENDAR_PATH) -> dict[str, str]` — 실패 시 `{}`
  - `save_calendar(days: dict, path: str = CALENDAR_PATH) -> None`
  - `load_access_token(path: str = TOKEN_CACHE_PATH) -> str | None`
  - `refresh_calendar(base_date: str) -> dict[str, str]` — 조회+저장. 실패 시 예외(위와 동일)
  - 상수 `CALENDAR_PATH = 'data/market_calendar.json'`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_market_calendar.py` 끝에 추가:

```python
import json

import pytest

import src.market_calendar as mc


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_fetch_calendar_sends_correct_tr_id(monkeypatch):
    """chk-holiday는 TR CTCA0903R로 실전 도메인에 조회한다."""
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        captured['url'] = url
        captured['headers'] = headers
        captured['params'] = params
        return _FakeResponse({
            'rt_cd': '0',
            'output': [{'bass_dt': '20260717', 'opnd_yn': 'N'}],
        })

    monkeypatch.setattr(mc.requests, 'get', fake_get)

    days = mc.fetch_calendar('TOKEN', 'KEY', 'SECRET', '20260717')

    assert days == {'20260717': 'N'}
    assert captured['headers']['tr_id'] == 'CTCA0903R'
    assert captured['headers']['authorization'] == 'Bearer TOKEN'
    assert captured['headers']['appkey'] == 'KEY'
    assert captured['params']['BASS_DT'] == '20260717'
    assert 'openapi.koreainvestment.com:9443' in captured['url']


def test_fetch_calendar_raises_on_api_error(monkeypatch):
    """rt_cd가 0이 아니면 예외다 — 빈 달력으로 폴백하지 않는다."""
    monkeypatch.setattr(mc.requests, 'get', lambda *a, **k: _FakeResponse(
        {'rt_cd': '1', 'msg1': 'EGW00123 토큰 오류'}
    ))
    with pytest.raises(RuntimeError, match='EGW00123'):
        mc.fetch_calendar('TOKEN', 'KEY', 'SECRET', '20260717')


def test_fetch_calendar_raises_on_empty_calendar(monkeypatch):
    """rt_cd=0인데 달력이 비면 예외다 — 판정 불가로 이어져야 한다."""
    monkeypatch.setattr(mc.requests, 'get', lambda *a, **k: _FakeResponse(
        {'rt_cd': '0', 'output': []}
    ))
    with pytest.raises(RuntimeError, match='비어'):
        mc.fetch_calendar('TOKEN', 'KEY', 'SECRET', '20260717')


def test_save_then_load_roundtrip(tmp_path):
    path = str(tmp_path / 'market_calendar.json')
    mc.save_calendar({'20260717': 'N', '20260720': 'Y'}, path=path)

    assert mc.load_calendar(path=path) == {'20260717': 'N', '20260720': 'Y'}

    saved = json.loads(open(path, encoding='utf-8').read())
    assert 'updated_at' in saved
    assert saved['days']['20260717'] == 'N'


def test_load_calendar_missing_file_returns_empty(tmp_path):
    """파일이 없으면 빈 맵 — lookup이 None(판정 불가)을 내도록."""
    assert mc.load_calendar(path=str(tmp_path / 'nope.json')) == {}


def test_load_calendar_corrupt_file_returns_empty(tmp_path):
    path = tmp_path / 'broken.json'
    path.write_text('{not json', encoding='utf-8')
    assert mc.load_calendar(path=str(path)) == {}


def test_load_access_token_missing_file(tmp_path):
    assert mc.load_access_token(path=str(tmp_path / 'nope.json')) is None


def test_load_access_token_reads_cache(tmp_path):
    path = tmp_path / 'token.json'
    path.write_text(json.dumps({'access_token': 'ABC'}), encoding='utf-8')
    assert mc.load_access_token(path=str(path)) == 'ABC'


def test_refresh_calendar_raises_without_credentials(monkeypatch):
    monkeypatch.delenv('KIS_APP_KEY', raising=False)
    monkeypatch.delenv('KIS_APP_SECRET', raising=False)
    with pytest.raises(RuntimeError, match='KIS_APP_KEY'):
        mc.refresh_calendar('20260717')


def test_refresh_calendar_raises_without_token(monkeypatch):
    monkeypatch.setenv('KIS_APP_KEY', 'KEY')
    monkeypatch.setenv('KIS_APP_SECRET', 'SECRET')
    monkeypatch.setattr(mc, 'load_access_token', lambda *a, **k: None)
    with pytest.raises(RuntimeError, match='토큰'):
        mc.refresh_calendar('20260717')


def test_refresh_calendar_fetches_and_saves(monkeypatch, tmp_path):
    path = str(tmp_path / 'market_calendar.json')
    monkeypatch.setenv('KIS_APP_KEY', 'KEY')
    monkeypatch.setenv('KIS_APP_SECRET', 'SECRET')
    monkeypatch.setattr(mc, 'load_access_token', lambda *a, **k: 'TOKEN')
    monkeypatch.setattr(mc, 'CALENDAR_PATH', path)
    monkeypatch.setattr(mc, 'fetch_calendar',
                        lambda *a, **k: {'20260717': 'N'})

    days = mc.refresh_calendar('20260717')

    assert days == {'20260717': 'N'}
    assert mc.load_calendar(path=path) == {'20260717': 'N'}
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_market_calendar.py -v`
Expected: FAIL — `AttributeError: module 'src.market_calendar' has no attribute 'requests'`

- [ ] **Step 3: 최소 구현을 쓴다**

`src/market_calendar.py` — 모듈 docstring 아래에 import·상수를 넣고, 파일 끝에 함수를 추가한다:

```python
import json
import os
from datetime import datetime, timedelta

import requests

CALENDAR_PATH = 'data/market_calendar.json'
TOKEN_CACHE_PATH = 'data/kis_token_cache.json'
CHK_HOLIDAY_URL = (
    "https://openapi.koreainvestment.com:9443"
    "/uapi/domestic-stock/v1/quotations/chk-holiday"
)
```

(`parse_calendar`, `lookup`은 Task 1 그대로 두고 그 아래에 추가:)

```python
def fetch_calendar(access_token: str, app_key: str, app_secret: str,
                   base_date: str) -> dict:
    """chk-holiday를 호출해 base_date부터의 달력을 받는다.

    실패는 예외다. 빈 달력으로 폴백하면 판정 불가가 개장으로 둔갑한다.
    """
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "CTCA0903R",
        "custtype": "P",
    }
    params = {"BASS_DT": base_date, "CTX_AREA_NK": "", "CTX_AREA_FK": ""}

    res = requests.get(CHK_HOLIDAY_URL, headers=headers, params=params, timeout=10)
    res.raise_for_status()
    data = res.json()

    if data.get('rt_cd') != '0':
        raise RuntimeError(f"chk-holiday 오류: {data.get('msg1', '')}")

    days = parse_calendar(data)
    if not days:
        raise RuntimeError("chk-holiday 응답의 달력이 비어 있다")
    return days


def load_calendar(path: str = None) -> dict:
    """저장된 달력을 읽는다. 없거나 깨졌으면 빈 맵."""
    try:
        with open(path or CALENDAR_PATH, 'r', encoding='utf-8') as f:
            return json.load(f).get('days', {})
    except Exception:
        return {}


def save_calendar(days: dict, path: str = None) -> None:
    """달력을 저장한다. updated_at은 디버깅용이며 판정에 쓰지 않는다."""
    target = path or CALENDAR_PATH
    payload = {
        'updated_at': (datetime.utcnow() + timedelta(hours=9)).isoformat(),
        'days': days,
    }
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(target, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def load_access_token(path: str = None) -> str:
    """token_manager가 남긴 로컬 캐시에서 토큰을 읽는다. 없으면 None."""
    try:
        with open(path or TOKEN_CACHE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f).get('access_token')
    except Exception:
        return None


def refresh_calendar(base_date: str) -> dict:
    """달력을 조회해 저장하고 반환한다. 실패는 예외."""
    app_key = os.environ.get('KIS_APP_KEY', '').strip()
    app_secret = os.environ.get('KIS_APP_SECRET', '').strip()
    if not app_key or not app_secret:
        raise RuntimeError("KIS_APP_KEY/KIS_APP_SECRET가 없다")

    token = load_access_token()
    if not token:
        raise RuntimeError("KIS 토큰 캐시가 없다")

    days = fetch_calendar(token, app_key, app_secret, base_date)
    save_calendar(days)
    return days
```

**주의:** `load_calendar`/`save_calendar`/`load_access_token`의 기본값을 `path: str = None`으로 두고 함수 안에서 `path or CALENDAR_PATH`로 푸는 이유는, 테스트가 `monkeypatch.setattr(mc, 'CALENDAR_PATH', ...)`로 상수를 갈아끼울 수 있게 하기 위함이다. 기본 인자에 상수를 직접 쓰면 import 시점에 값이 박혀 monkeypatch가 먹지 않는다.

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_market_calendar.py -v`
Expected: PASS (19 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/market_calendar.py tests/test_market_calendar.py
git commit -m "feat(holiday): 달력 조회·저장·갱신 I/O 추가

fetch_calendar는 실패를 예외로 올린다. 빈 달력 폴백은
판정 불가를 개장으로 둔갑시키므로 금지한다.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `is_trading_day()` 3값 판정 + FORCE_RUN + holidays 제거

문제의 핵심을 고친다. 없는 필드(`bzdy_tp_cd`)를 읽던 로직과 holidays 폴백을 걷어내고, 판정 불가를 개장과 구분한다.

**Files:**
- Modify: `src/pipeline/context.py:79-155` (`is_trading_day`, `_check_trading_day_via_kis`), `:176-199` (`is_market_hours`, `is_after_market_close`)
- Modify: `scripts/requirements-scraper.txt:7` (`holidays` 제거)
- Test: `tests/test_market_holiday_gate.py`

**Interfaces:**
- Consumes: `load_calendar()`, `lookup(days, yyyymmdd)`, `refresh_calendar(base_date)` (Task 2)
- Produces:
  - `PipelineContext.is_trading_day() -> bool | None` — `True`/`False`/`None`(판정 불가)
  - `PipelineContext.is_market_hours() -> bool` — 판정 불가면 `False`
  - `PipelineContext.is_after_market_close() -> bool` — 판정 불가면 `False`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_market_holiday_gate.py` 생성:

```python
"""휴장일 게이트 회귀 테스트.

2026-07-17(공휴일)에 스크래퍼가 돌고 텔레그램이 나간 사고의 재발을 막는다.
원인: chk-holiday 응답에 없는 필드(bzdy_tp_cd)를 읽어 opnd_yn을 놓쳤고,
holidays 0.86이 2026-07-17을 몰랐으며, 판정 실패가 조용히 개장으로 통과했다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime

import pytest

import src.market_calendar as mc
from src.pipeline.context import PipelineContext


def ctx_at(when: datetime) -> PipelineContext:
    ctx = object.__new__(PipelineContext)
    ctx.now_kst = when
    ctx.today_str = when.strftime('%Y%m%d')
    ctx.today_display = when.strftime('%Y.%m.%d')
    return ctx


@pytest.fixture(autouse=True)
def _no_force_run(monkeypatch):
    """FORCE_RUN이 셸에 남아 있으면 게이트 테스트가 전부 무의미해진다."""
    monkeypatch.delenv('FORCE_RUN', raising=False)


# ── 달력 기반 판정 ──

def test_holiday_20260717_is_closed(monkeypatch):
    """2026-07-17(금)은 휴장이다 — 이 사고의 회귀 테스트.

    평일이라 주말 조기 반환에 걸리지 않는다. 달력 경로가 실제로 판정한다.
    """
    monkeypatch.setattr(mc, 'load_calendar', lambda *a, **k: {'20260717': 'N'})
    assert ctx_at(datetime(2026, 7, 17, 10, 0)).is_trading_day() is False


def test_open_day_from_calendar(monkeypatch):
    """2026-07-20(월) 개장."""
    monkeypatch.setattr(mc, 'load_calendar', lambda *a, **k: {'20260720': 'Y'})
    assert ctx_at(datetime(2026, 7, 20, 10, 0)).is_trading_day() is True


def test_weekend_is_closed_without_api(monkeypatch):
    """주말(2026-07-18 토)은 API·달력을 건드리지 않고 즉시 휴장."""
    def _boom(*a, **k):
        raise AssertionError("주말엔 달력을 읽지 않아야 한다")
    monkeypatch.setattr(mc, 'load_calendar', _boom)
    assert ctx_at(datetime(2026, 7, 18, 10, 0)).is_trading_day() is False


# ── 재조회 계층 ──

def test_refetches_when_today_missing(monkeypatch):
    """달력에 오늘이 없으면 직접 조회한다."""
    monkeypatch.setattr(mc, 'load_calendar', lambda *a, **k: {'20260101': 'N'})
    monkeypatch.setattr(mc, 'refresh_calendar', lambda base: {'20260720': 'Y'})
    assert ctx_at(datetime(2026, 7, 20, 10, 0)).is_trading_day() is True


def test_refetch_failure_is_none(monkeypatch):
    """재조회가 실패하면 판정 불가(None)다. True가 아니다."""
    monkeypatch.setattr(mc, 'load_calendar', lambda *a, **k: {})

    def _fail(base):
        raise RuntimeError("KIS 장애")
    monkeypatch.setattr(mc, 'refresh_calendar', _fail)

    assert ctx_at(datetime(2026, 7, 20, 10, 0)).is_trading_day() is None


def test_refetch_without_today_is_none(monkeypatch):
    """재조회는 성공했는데 응답에 오늘이 없으면 판정 불가."""
    monkeypatch.setattr(mc, 'load_calendar', lambda *a, **k: {})
    monkeypatch.setattr(mc, 'refresh_calendar', lambda base: {'20260721': 'Y'})
    assert ctx_at(datetime(2026, 7, 20, 10, 0)).is_trading_day() is None


# ── FORCE_RUN 탈출구 ──

def test_force_run_bypasses_gate(monkeypatch):
    """KIS 장애 시 수동 실행 수단. 휴장 판정도 우회한다."""
    monkeypatch.setenv('FORCE_RUN', 'true')
    monkeypatch.setattr(mc, 'load_calendar', lambda *a, **k: {'20260717': 'N'})
    assert ctx_at(datetime(2026, 7, 17, 10, 0)).is_trading_day() is True


def test_force_run_false_does_not_bypass(monkeypatch):
    """workflow_dispatch 기본값이 'false' 문자열로 넘어온다."""
    monkeypatch.setenv('FORCE_RUN', 'false')
    monkeypatch.setattr(mc, 'load_calendar', lambda *a, **k: {'20260717': 'N'})
    assert ctx_at(datetime(2026, 7, 17, 10, 0)).is_trading_day() is False


def test_force_run_empty_does_not_bypass(monkeypatch):
    """repository_dispatch에선 inputs가 없어 빈 문자열이 넘어온다."""
    monkeypatch.setenv('FORCE_RUN', '')
    monkeypatch.setattr(mc, 'load_calendar', lambda *a, **k: {'20260717': 'N'})
    assert ctx_at(datetime(2026, 7, 17, 10, 0)).is_trading_day() is False


# ── 실거래 게이트는 판정 불가 시 닫힌다 ──

def test_market_hours_closed_when_undetermined(monkeypatch):
    """판정 불가면 매수 게이트는 닫힌다. None이 아니라 False를 반환해야 한다."""
    monkeypatch.setattr(PipelineContext, 'is_trading_day', lambda self: None)
    assert ctx_at(datetime(2026, 7, 20, 10, 0)).is_market_hours() is False


def test_after_close_closed_when_undetermined(monkeypatch):
    monkeypatch.setattr(PipelineContext, 'is_trading_day', lambda self: None)
    assert ctx_at(datetime(2026, 7, 20, 16, 0)).is_after_market_close() is False


def test_holidays_package_not_imported():
    """holidays 패키지 폴백은 제거됐다 — 신규 지정 공휴일을 못 잡는다.

    import 문만 본다. 왜 안 쓰는지 설명하는 주석·docstring은 남겨둬야 하므로
    소스 전체에서 'holidays' 문자열을 찾으면 그 설명에 자기 자신이 걸린다.
    """
    import inspect
    from src.pipeline import context
    source = inspect.getsource(context)
    assert 'import holidays' not in source
    assert 'from holidays' not in source
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_market_holiday_gate.py -v`
Expected: FAIL — `test_holidays_package_not_imported`가 실패하고, 달력 관련 테스트도 실패한다 (현재 `is_trading_day`는 달력을 모른다).

- [ ] **Step 3: `is_trading_day`를 다시 쓴다**

`src/pipeline/context.py:79-155`의 `is_trading_day`와 `_check_trading_day_via_kis`를 **통째로** 아래로 교체한다 (`_check_trading_day_via_kis`는 삭제한다 — 로직이 `market_calendar`로 옮겨갔다):

```python
    def is_trading_day(self):
        """오늘이 개장일인지 판정한다.

        True=개장, False=휴장, None=판정 불가.

        [주의] None은 개장이 아니다. 호출부는 fail-closed로 닫아야 한다.
        판정 실패를 True로 폴백하면 휴장일에 봇이 돈다 (2026-07-17 사고).

        판정 소스는 KIS chk-holiday 하나다. holidays 패키지는 신규 지정·
        임시공휴일을 모르므로(0.86이 2026-07-17을 놓쳤다) 쓰지 않는다.
        """
        if os.environ.get('FORCE_RUN', '').strip().lower() == 'true':
            self.log("[FORCE_RUN] 휴장일 게이트를 우회합니다.")
            return True

        if self.now_kst.weekday() >= 5:
            return False

        from src.market_calendar import load_calendar, lookup, refresh_calendar

        result = lookup(load_calendar(), self.today_str)
        if result is not None:
            return result

        # 달력에 오늘이 없다 (07시 갱신 런 실패 등) → 직접 조회
        self.log(f"[휴장 판정] 달력에 {self.today_str}이 없어 직접 조회합니다.")
        try:
            days = refresh_calendar(self.today_str)
        except Exception as e:
            self.log(f"[휴장 판정 실패] chk-holiday 조회 실패: {e}")
            return None

        result = lookup(days, self.today_str)
        if result is None:
            self.log(f"[휴장 판정 실패] 조회한 달력에 {self.today_str}이 없습니다.")
        else:
            self.log(f"[휴장 판정] {self.today_str} 개장={result}")
        return result
```

- [ ] **Step 4: 실거래 게이트의 반환 타입을 좁힌다**

`is_trading_day()`가 `None`을 낼 수 있게 되면서 `None and X` → `None`이 그대로
반환값으로 샌다 (`-> bool` 위반). 두 메서드를 **통째로** 아래로 교체한다
(`src/pipeline/context.py:176-199`):

```python
    def is_market_hours(self) -> bool:
        """장중 시간대(09:00~15:50)에 해당하는지 확인합니다.

        [주의] 실거래 게이트다 (trade_engine의 allow_buy, program_trader).
        장은 15:30에 닫지만 이 상한은 15:50이다. 마감 후 판정에는
        is_after_market_close()를 쓸 것 — 여기를 낮추면 매수 허용 시간대가 바뀐다.

        거래일 판정 불가(None)면 닫는다. 거래일인지 모르는 채로 매수하지 않는다.
        """
        return bool(
            self.is_trading_day() is True and
            9 <= self.now_kst.hour < 16 and
            not (self.now_kst.hour == 15 and self.now_kst.minute >= 50)
        )

    def is_after_market_close(self) -> bool:
        """거래일의 장 마감(15:30) 이후인지 확인합니다.

        is_market_hours()와 15:30~15:49 구간이 겹친다. 둘을 함께 쓰는 곳은
        이쪽을 먼저 판정해야 한다.

        거래일 판정 불가(None)면 닫는다.
        """
        if self.now_kst.weekday() >= 5:
            return False
        if (self.now_kst.hour, self.now_kst.minute) < MARKET_CLOSE_HHMM:
            return False
        return self.is_trading_day() is True
```

- [ ] **Step 5: `holidays` 의존성을 제거한다**

`scripts/requirements-scraper.txt`에서 `holidays` 줄을 삭제한다:

```diff
 pypdf
 pdfplumber
-holidays
 google-genai
```

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_market_holiday_gate.py -v`
Expected: PASS (12 passed)

- [ ] **Step 7: 기존 테스트가 깨지지 않았는지 확인한다**

Run: `python -m pytest tests/test_libero_eod_and_leak.py tests/test_market_calendar.py -v`
Expected: PASS — `test_libero_eod_and_leak.py`는 `is_trading_day`를 monkeypatch하므로 영향받지 않아야 한다. 만약 `is ...` 비교에서 실패하면 Step 4의 타입 좁히기가 빠진 것이다.

- [ ] **Step 8: 커밋**

```bash
git add src/pipeline/context.py scripts/requirements-scraper.txt tests/test_market_holiday_gate.py
git commit -m "fix(holiday): 휴장 판정을 opnd_yn 기반 3값 + fail-closed로 교체

2026-07-17 휴장일에 스크래퍼가 돌던 문제의 본 수정.

- 응답 스펙에 없는 bzdy_tp_cd를 읽던 로직 제거 → 달력의 opnd_yn 사용
- holidays 폴백 제거 (0.86이 2026-07-17을 모름)
- 판정 실패 시 True 폴백 → None(판정 불가). 개장과 구분한다
- is_market_hours/is_after_market_close는 None을 False로 좁힌다
- FORCE_RUN 구현 (죽어 있던 env) — fail-closed의 수동 탈출구

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: 오케스트레이터 fail-closed 게이트 + 경고 발송

판정 불가를 중단으로 연결하고 경고를 보낸다.

**Files:**
- Modify: `src/pipeline/orchestrator.py:46-49` (휴장일 체크 블록)
- Test: `tests/test_market_holiday_gate.py` (Task 3 파일에 추가)

**Interfaces:**
- Consumes: `PipelineContext.is_trading_day() -> bool | None` (Task 3), `TelegramManager.send_message(text, parse_mode="HTML") -> bool`
- Produces: `_notify_holiday_check_failed(ctx: PipelineContext) -> None`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_market_holiday_gate.py` 끝에 추가:

```python
# ── 오케스트레이터 게이트 ──

def _stub_workers(monkeypatch):
    """Stage 1이 돌면 테스트가 네트워크를 탄다. 돌면 즉시 실패시킨다."""
    from src.pipeline import orchestrator

    def _boom(*a, **k):
        raise AssertionError("게이트가 열려 파이프라인이 진행됐다")

    monkeypatch.setattr(orchestrator, 'DataFetcherWorker', _boom)
    monkeypatch.setattr(orchestrator, 'StorageManager', lambda *a, **k: None)


def test_pipeline_stops_and_warns_when_undetermined(monkeypatch):
    """판정 불가면 중단하고 경고를 보낸다."""
    from src.pipeline import orchestrator

    _stub_workers(monkeypatch)
    sent = []
    monkeypatch.setattr(orchestrator, '_notify_holiday_check_failed',
                        lambda ctx: sent.append(ctx.today_str))
    monkeypatch.setattr(PipelineContext, 'is_trading_day', lambda self: None)

    ctx = ctx_at(datetime(2026, 7, 20, 10, 0))
    orchestrator.run_pipeline(ctx)   # 예외 없이 조용히 끝나야 한다

    assert sent == ['20260720']


def test_pipeline_stops_without_warning_on_holiday(monkeypatch):
    """휴장은 정상 상태다 — 경고를 보내지 않는다."""
    from src.pipeline import orchestrator

    _stub_workers(monkeypatch)
    sent = []
    monkeypatch.setattr(orchestrator, '_notify_holiday_check_failed',
                        lambda ctx: sent.append(ctx.today_str))
    monkeypatch.setattr(PipelineContext, 'is_trading_day', lambda self: False)

    orchestrator.run_pipeline(ctx_at(datetime(2026, 7, 17, 10, 0)))

    assert sent == []


def test_warning_bypasses_should_notify(monkeypatch):
    """경고는 should_notify()의 정각 제한을 타지 않는다.

    15/30/45분 런에서 침묵하면 장애를 놓친다.
    """
    from src.pipeline import orchestrator

    monkeypatch.setattr(PipelineContext, 'should_notify',
                        lambda self: (_ for _ in ()).throw(
                            AssertionError("경고는 should_notify를 호출하면 안 된다")))

    messages = []

    class _FakeTelegram:
        def send_message(self, text, parse_mode="HTML"):
            messages.append(text)
            return True

    monkeypatch.setattr('src.telegram_manager.TelegramManager',
                        lambda *a, **k: _FakeTelegram())

    ctx = ctx_at(datetime(2026, 7, 20, 10, 45))   # 정각이 아닌 런
    orchestrator._notify_holiday_check_failed(ctx)

    assert len(messages) == 1
    assert '휴장 판정 실패' in messages[0]
    assert 'FORCE_RUN' in messages[0] or 'force_run' in messages[0]
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/test_market_holiday_gate.py -k "pipeline or warning" -v`
Expected: FAIL — `AttributeError: module 'src.pipeline.orchestrator' has no attribute '_notify_holiday_check_failed'`

- [ ] **Step 3: 경고 함수를 추가한다**

`src/pipeline/orchestrator.py`의 `active_only` 함수 아래, `run_pipeline` 위에 추가한다:

```python
def _notify_holiday_check_failed(ctx: PipelineContext) -> None:
    """거래일 판정 불가를 알린다.

    should_notify()의 정각(0~2분) 제한을 일부러 우회한다 — 이건 리포트가
    아니라 "봇이 멈췄다"는 장애 신호이고, 15/30/45분 런에서 침묵하면
    장애를 놓친다.
    """
    try:
        from src.telegram_manager import TelegramManager
        TelegramManager().send_message(
            f"⚠️ <b>휴장 판정 실패</b>\n\n"
            f"{ctx.today_display} — 거래일 여부를 확인하지 못해 봇을 정지했습니다.\n"
            f"KIS chk-holiday 조회에 실패했습니다.\n\n"
            f"수동 실행: scraper.yml → Run workflow → FORCE_RUN=true"
        )
    except Exception as e:
        ctx.log(f"[경고] 판정 실패 알림 발송에 실패했습니다: {e}")
```

- [ ] **Step 4: 게이트를 3값으로 바꾼다**

`src/pipeline/orchestrator.py:46-49`를 교체한다:

```python
    # ── 휴장일 체크 ──────────────────────────────────────────
    # is_trading_day()는 3값이다. None(판정 불가)을 휴장과 뭉뚱그리면
    # 조용히 멈추고, True로 폴백하면 휴장일에 돈다. 둘 다 갈라서 처리한다.
    trading = ctx.is_trading_day()
    if trading is None:
        ctx.log(f"[중단] 거래일 여부를 판정할 수 없습니다({ctx.today_display}).")
        _notify_holiday_check_failed(ctx)
        return
    if not trading:
        ctx.log(f"오늘은 휴장일({ctx.today_display})입니다. 파이프라인을 종료합니다.")
        return
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/test_market_holiday_gate.py -v`
Expected: PASS (15 passed)

- [ ] **Step 6: 커밋**

```bash
git add src/pipeline/orchestrator.py tests/test_market_holiday_gate.py
git commit -m "feat(holiday): 판정 불가 시 파이프라인 중단 + 경고 발송

휴장(정상)과 판정 불가(장애)를 갈라서 처리한다. 경고는
should_notify()의 정각 제한을 우회한다 — 리포트가 아니라
장애 신호이므로 15/30/45분 런에서도 나가야 한다.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: 07시 달력 갱신 (스크립트 + 워크플로우)

토큰 발급 직후 달력을 받아 db-data에 올린다.

**Files:**
- Create: `scripts/update_market_calendar.py`
- Modify: `.github/workflows/token_refresh.yml`

**Interfaces:**
- Consumes: `refresh_calendar(base_date: str) -> dict[str, str]` (Task 2), `CALENDAR_PATH = 'data/market_calendar.json'`
- Produces: db-data 브랜치의 `data/market_calendar.json`

- [ ] **Step 1: 갱신 스크립트를 쓴다**

`scripts/update_market_calendar.py` 생성:

```python
"""07시 토큰 발급 직후 KIS 개장일 달력을 갱신한다.

token_manager.py가 data/kis_token_cache.json에 토큰을 남긴 뒤 실행되어야 한다.
실패는 exit 1이다 — 조용히 넘어가면 스크래퍼가 판정 불가로 정지한다.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.market_calendar import refresh_calendar


def main():
    today = (datetime.utcnow() + timedelta(hours=9)).strftime('%Y%m%d')
    try:
        days = refresh_calendar(today)
    except Exception as e:
        print(f"[MarketCalendar] 갱신 실패: {e}")
        sys.exit(1)

    opnd = days.get(today, '?')
    print(f"[MarketCalendar] {len(days)}일치 저장 완료. "
          f"오늘({today}) 개장여부={opnd}")


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: 로컬에서 실패 경로를 확인한다**

자격증명 없이 돌려 fail 경로가 살아있는지 본다.

Run: `cd /c/Users/Hoon_DT/gemini/stock && KIS_APP_KEY= KIS_APP_SECRET= python scripts/update_market_calendar.py; echo "exit=$?"`
Expected: `[MarketCalendar] 갱신 실패: KIS_APP_KEY/KIS_APP_SECRET가 없다` 와 `exit=1`

- [ ] **Step 3: 워크플로우에 갱신 + 배포 스텝을 추가한다**

`.github/workflows/token_refresh.yml`의 `Manage KIS Token` 스텝(현재 마지막) **아래**에 두 스텝을 추가한다:

```yaml
      # 토큰이 발급된 직후에만 달력을 받을 수 있다 (chk-holiday도 토큰이 필요).
      # 달력은 3개월치라, 이 런이 하루 실패해도 이전 저장분에 오늘이 들어있다.
      - name: Update market calendar
        env:
          KIS_APP_KEY: ${{ secrets.KIS_APP_KEY }}
          KIS_APP_SECRET: ${{ secrets.KIS_APP_SECRET }}
        run: PYTHONPATH=. python scripts/update_market_calendar.py

      # 달력은 자격증명이 아니므로 public db-data에 둔다.
      # 스크래퍼가 시작 시 `git checkout db-data -- data/`로 읽어간다.
      - name: Deploy calendar to db-data
        run: |
          git config --global user.email "github-actions[bot]@users.noreply.github.com"
          git config --global user.name "github-actions[bot]"
          git clone --branch db-data --depth 1 \
            https://x-access-token:${{ secrets.GITHUB_TOKEN }}@github.com/${{ github.repository }}.git db_data_repo
          mkdir -p db_data_repo/data
          cp data/market_calendar.json db_data_repo/data/
          cd db_data_repo
          git add data/market_calendar.json
          git diff --staged --quiet || git commit -m "chore(calendar): 개장일 달력 갱신 [skip ci]"
          git push origin db-data
```

`permissions`가 없으면 push가 403이 난다. `jobs.refresh` 아래 `runs-on` 옆에 추가한다:

```yaml
  refresh:
    runs-on: ubuntu-latest
    permissions:
      contents: write
```

- [ ] **Step 4: YAML 문법을 검증한다**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/token_refresh.yml', encoding='utf-8')); print('YAML OK')"`
Expected: `YAML OK`

- [ ] **Step 5: 커밋**

```bash
git add scripts/update_market_calendar.py .github/workflows/token_refresh.yml
git commit -m "feat(holiday): 07시 토큰 발급 직후 개장일 달력 갱신

chk-holiday도 토큰이 필요하므로 발급 이후에만 조회할 수 있다.
달력은 3개월치라 이 런이 하루 실패해도 이전 저장분으로 버틴다.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: 전체 테스트 + 실측 검증

**Files:**
- Test: 전체

**Interfaces:**
- Consumes: Task 1-5의 모든 산출물
- Produces: 없음 (검증만)

- [ ] **Step 1: 전체 테스트를 돌린다**

Run: `python -m pytest tests/ -q`
Expected: 전부 PASS. 실패가 있으면 이번 변경과 무관한 기존 실패인지 `git stash`로 확인한다.

- [ ] **Step 2: 휴장 판정 경로에 holidays 잔재가 없는지 확인한다**

Run: `grep -rn "import holidays\|from holidays" src/ scripts/`

Expected: **`src/analyzer_5days.py:12` 한 곳만** 매치한다. 이번 스코프 밖이며 **손대지 않는다.**

`get_recent_working_days()`가 `holidays.KR()`로 5영업일을 계산해 같은 결함(2026-07-17을 영업일로
봄)을 갖지만, **스크래퍼 런타임 import 체인에 없고** `analyze_cumulative()`는 파이프라인
어디서도 호출되지 않는다 (import 그래프 추적 + grep 확인). 별도 이슈다.

`src/pipeline/context.py`와 `scripts/requirements-scraper.txt`에서는 매치가 **없어야** 한다.

**`scripts/scraper_legacy_v49.py:42-43`은 이 패턴에 걸리지 않는다** — `import`가 아니라
`holidays_2026`이라는 로컬 변수에 2026년 공휴일을 하드코딩한 리스트다(`07-17` 없음, 같은 종류의
결함). V49 시절 죽은 레거시로 현재 파이프라인이 import하지 않으므로 역시 손대지 않는다.

`scripts/requirements.txt`(스크래퍼용이 아닌 별도 파일)의 `holidays==0.86` 핀도
`analyzer_5days.py`가 쓰므로 **그대로 둔다** — 여기서 빼면 그 모듈이 ImportError로 죽는다.

- [ ] **Step 3: 달력 파일이 배포 제외 목록에 걸리지 않는지 확인한다**

`scraper.yml`의 `Deploy Data to db-data branch` 스텝은 `data/*.json`을 배포하되
블랙리스트(`kis_token_cache.json` 등)만 `case` 문으로 거른다. 스크래퍼가 재조회로
갱신한 달력도 db-data에 반영되려면 `market_calendar.json`이 그 목록에 **없어야** 한다.

Run: `grep -n "market_calendar" .github/workflows/scraper.yml`
Expected: 출력 없음 (블랙리스트에 없으므로 `data/*.json` 규칙에 따라 자동 배포된다).

- [ ] **Step 4: 커밋 (변경이 있다면)**

```bash
git status --short
```

변경이 없으면 커밋하지 않는다.

---

## 배포 후 실측 검증 (사람이 한다)

머지 후 다음 거래일 07시 런에서 확인한다. 이 계획의 코드 변경으로는 검증할 수 없는 항목들이다.

- [ ] `token_refresh.yml` 런 로그에 `[MarketCalendar] N일치 저장 완료. 오늘(YYYYMMDD) 개장여부=Y`가 찍히는지
- [ ] db-data 브랜치에 `data/market_calendar.json`이 생겼고 `days`에 3개월치가 들어있는지
- [ ] **`opnd_yn` 필드명이 실제 응답에 존재하는지** — 이 계획은 KIS 문서 스펙을 근거로 하며, 라이브 응답으로 확인되지 않았다. 필드명이 다르면 `parse_calendar`가 빈 맵을 내고 `fetch_calendar`가 예외를 던져 fail-closed로 정지한다 (조용히 틀리지는 않는다).
- [ ] 거래일 스크래퍼 런에서 `[휴장 판정] ... 개장=True` 로그가 찍히고 파이프라인이 정상 진행되는지
- [ ] 다음 휴장일에 스크래퍼가 즉시 종료되고 텔레그램이 오지 않는지
