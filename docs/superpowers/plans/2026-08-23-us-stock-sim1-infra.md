# 미국 주식 페이퍼 심 — 공용 인프라 + US Sim1(미너비니) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 국내 매매 파이프라인을 전혀 건드리지 않고, 완전히 병렬인 새 트랙으로 미국 주식
페이퍼(관찰) 심 1개(US Sim1, 미너비니 추세형)를 처음부터 끝까지(유니버스 → EOD 워치리스트
배치 → 장중 페이퍼 체결 루프 → `/trade/us` 대시보드)까지 완성한다.

**Architecture:** 유니버스(nasdaq 스크리너)·일봉(Yahoo Finance)·펀더멘털(SEC EDGAR)
데이터 소스를 각각 순수 함수 모듈로 만들고, 이를 소비하는 `USMinerviniSimulator`가
`BaseSimulator`를 상속(단 KRW 수수료·정수가격 절사를 흡수하는 `USBaseSimulator`를 한 단계
사이에 둔다)한다. 심 등록은 국내 `strategy_manifest.yaml`과 완전히 분리된
`us_strategy_manifest.yaml`/`us_registry.py`로 관리해 국내 60초 루프
(`trade_engine._run_simulators`)가 US 심을 절대 건드리지 않게 한다. EOD 배치는 하루 1회
무거운 계산(추세템플릿·SEPA·VCP)을 감시목록으로 남기고, 장중 루프는 GitHub Actions 네이티브
cron + `zoneinfo` 게이트로 감시목록 종목만 폴링해 페이퍼 체결한다.

**Tech Stack:** Python 3.10(백엔드 스크립트/심), TypeScript/Next.js 14 + Mantine 7(프론트),
pytest(파이썬 테스트), `node --test`(TS 테스트), GitHub Actions(스케줄링·배포).

**Spec:** `docs/superpowers/specs/2026-08-23-us-stock-paper-sims-design.md`

## Global Constraints

- 페이퍼 전용 — 실주문(KIS 해외주식 API) 연동 없음, 자본 이동 없음.
- 국내 파이프라인(`strategy_manifest.yaml`, `trade_engine.py`, `registry.py`,
  `sim-reset-targets.ts`, `/api/simulation/reset`, `/api/simulation/stats`,
  `/trade` URL)은 **수정하지 않는다** — 단, `TradeClient.tsx`의 헤더 문구/네비게이션
  추가, `SimCard.tsx`/`PortfolioTable.tsx`의 `currency` prop 추가(기본값 `'KRW'`로
  기존 동작 100% 보존)는 허용된 최소 additive 변경이다.
- 통화는 USD 그대로, 환율 변환 없음.
- 유니버스: `api.nasdaq.com/api/screener/stocks`(exchange=nasdaq,nyse,amex), 키 불필요.
- 일봉: Yahoo Finance 비공식 chart API(`query1.finance.yahoo.com/v8/finance/chart/{symbol}`).
- 펀더멘털: SEC EDGAR(`data.sec.gov`, `www.sec.gov/files/company_tickers.json`), 키 불필요,
  User-Agent 헤더 필수, 10 req/s 이하.
- 조회 실패는 0으로 폴백하지 않는다 — `None`으로 "측정 불가"를 표현한다
  (`[[no-fabricated-financial-values]]` 관례).
- 심 파라미터(비중 19%, 최대 5종목, 손절 -7.5%, 50일선 이탈청산 등)는 국내 Sim11
  (`src/strategy/simulators/sim11_minervini.py`)과 동일한 값을 그대로 쓴다.
- 초기 페이퍼 자본은 하드코딩하지 않는다 — 리셋 API가 받는 값을 그대로 쓴다.
  각 US 심 클래스(`__init__(self, initial_cash=20000)`)의 기본값만 `$20,000`
  (리셋 전 최초 기동용 placeholder).
- USD 리셋 검증 범위: `$1,000 ~ $500,000` 정수.
- 테스트 실행: `python -m pytest tests/ -q`(파이썬), `node --test "src/**/*.test.ts"` +
  `npx tsc --noEmit`(TS) — `.github/workflows/tests.yml`과 동일 명령.

---

## Task 1: 유니버스 소스 (`src/data/us_universe.py`)

**Files:**
- Create: `src/data/us_universe.py`
- Test: `tests/test_us_universe.py`

**Interfaces:**
- Produces:
  - `fetch_us_universe(limit: int = 1000) -> list[dict]` — 각 항목
    `{'symbol': str, 'name': str, 'market_cap': float | None, 'country': str, 'sector': str | None}`.
    네트워크 실패 시 예외를 올린다(호출부가 잡는다) — 빈 리스트로 조용히 넘어가지 않는다.
  - `filter_universe(rows: list[dict]) -> list[dict]` — ETF/워런트/우선주 및
    `symbol`에 `.`, `^`, `/`가 들어간 항목 제외, `market_cap`이 없거나 0인 항목 제외.
  - `save_universe(rows: list[dict], path: str) -> None`
  - `load_universe(path: str) -> list[dict]` — 파일 없거나 파싱 실패 시 빈 리스트.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_us_universe.py
import json
import os
import tempfile
from unittest import mock

from src.data.us_universe import fetch_us_universe, filter_universe, save_universe, load_universe

NASDAQ_RESPONSE = {
    "data": {
        "rows": [
            {"symbol": "AAPL", "name": "Apple Inc. Common Stock", "marketCap": "3400000000000",
             "country": "United States", "sector": "Technology"},
            {"symbol": "QQQ", "name": "Invesco QQQ Trust", "marketCap": "",
             "country": "", "sector": ""},
            {"symbol": "BABA", "name": "Alibaba Group ADR", "marketCap": "220000000000",
             "country": "China", "sector": "Consumer Discretionary"},
            {"symbol": "BRK^A", "name": "Berkshire Hathaway", "marketCap": "900000000000",
             "country": "United States", "sector": "Financial"},
        ]
    },
    "message": None,
    "status": {"rCode": 200},
}


def test_fetch_us_universe_parses_rows():
    with mock.patch('src.data.us_universe.requests.get') as m:
        m.return_value.status_code = 200
        m.return_value.json.return_value = NASDAQ_RESPONSE
        m.return_value.raise_for_status = lambda: None
        rows = fetch_us_universe(limit=10)
    assert len(rows) == 4
    aapl = next(r for r in rows if r['symbol'] == 'AAPL')
    assert aapl['market_cap'] == 3400000000000.0
    assert aapl['country'] == 'United States'


def test_fetch_us_universe_raises_on_http_error():
    with mock.patch('src.data.us_universe.requests.get') as m:
        m.return_value.raise_for_status.side_effect = Exception('boom')
        try:
            fetch_us_universe(limit=10)
            assert False, '예외가 나야 한다'
        except Exception:
            pass


def test_filter_universe_excludes_etf_and_missing_marketcap():
    rows = fetch_us_universe.__wrapped__ if False else None  # placeholder not used
    raw = [
        {'symbol': 'AAPL', 'name': 'Apple Inc.', 'market_cap': 3.4e12, 'country': 'United States', 'sector': 'Technology'},
        {'symbol': 'QQQ', 'name': 'Invesco QQQ Trust', 'market_cap': None, 'country': '', 'sector': None},
        {'symbol': 'BRK^A', 'name': 'Berkshire', 'market_cap': 9e11, 'country': 'United States', 'sector': 'Financial'},
        {'symbol': 'ZERO', 'name': 'Zero Cap', 'market_cap': 0, 'country': 'United States', 'sector': 'Tech'},
    ]
    out = filter_universe(raw)
    symbols = {r['symbol'] for r in out}
    assert symbols == {'AAPL'}


def test_save_and_load_roundtrip():
    rows = [{'symbol': 'AAPL', 'name': 'Apple Inc.', 'market_cap': 3.4e12,
             'country': 'United States', 'sector': 'Technology'}]
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'us_universe.json')
        save_universe(rows, path)
        loaded = load_universe(path)
    assert loaded == rows


def test_load_universe_missing_file_returns_empty():
    assert load_universe('/no/such/path/us_universe.json') == []
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_us_universe.py -q`
Expected: FAIL(`ModuleNotFoundError: No module named 'src.data.us_universe'`)

- [ ] **Step 3: 구현**

```python
# src/data/us_universe.py
"""미국 주식 유니버스 소스 — 네이버 시총랭킹의 미국판.

api.nasdaq.com 스크리너는 키가 필요 없고 나스닥·NYSE·AMEX 상장 전체를
시가총액 포함해 JSON으로 준다. ETF·우선주·워런트는 심볼에 `.`/`^`/`/`가
섞이거나 marketCap이 비는 경우가 많아 그걸로 거른다 — 완벽하지는 않지만
추가 조회 없이 되는 선에서의 근사다.
"""
import json
import os

import requests

NASDAQ_SCREENER_URL = 'https://api.nasdaq.com/api/screener/stocks'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
}


def _to_float(v):
    try:
        v = str(v).replace(',', '').strip()
        return float(v) if v else None
    except (TypeError, ValueError):
        return None


def fetch_us_universe(limit: int = 1000) -> list[dict]:
    """나스닥 스크리너에서 미국 상장 종목을 가져온다. 실패하면 예외를 올린다."""
    params = {
        'tableonly': 'true',
        'limit': str(limit),
        'offset': '0',
        'exchange': 'nasdaq,nyse,amex',
        'download': 'true',
    }
    r = requests.get(NASDAQ_SCREENER_URL, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    body = r.json()
    rows = ((body or {}).get('data') or {}).get('rows') or []
    out = []
    for row in rows:
        out.append({
            'symbol': row.get('symbol', ''),
            'name': row.get('name', ''),
            'market_cap': _to_float(row.get('marketCap')),
            'country': row.get('country', ''),
            'sector': row.get('sector') or None,
        })
    return out


def filter_universe(rows: list[dict]) -> list[dict]:
    """ETF/우선주/워런트 및 시총 결손 종목을 제외한다."""
    out = []
    for r in rows:
        symbol = r.get('symbol', '')
        if not symbol or any(c in symbol for c in ('.', '^', '/')):
            continue
        mc = r.get('market_cap')
        if not mc or mc <= 0:
            continue
        out.append(r)
    return out


def save_universe(rows: list[dict], path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def load_universe(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding='utf-8-sig') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_us_universe.py -q`
Expected: PASS(5 passed)

- [ ] **Step 5: `test_filter_universe_excludes_etf_and_missing_marketcap`의 죽은 줄 정리**

Step 1에서 실수로 넣은 미사용 줄(`rows = fetch_us_universe.__wrapped__ ...`)을 지운다.

```python
def test_filter_universe_excludes_etf_and_missing_marketcap():
    raw = [
        {'symbol': 'AAPL', 'name': 'Apple Inc.', 'market_cap': 3.4e12, 'country': 'United States', 'sector': 'Technology'},
        {'symbol': 'QQQ', 'name': 'Invesco QQQ Trust', 'market_cap': None, 'country': '', 'sector': None},
        {'symbol': 'BRK^A', 'name': 'Berkshire', 'market_cap': 9e11, 'country': 'United States', 'sector': 'Financial'},
        {'symbol': 'ZERO', 'name': 'Zero Cap', 'market_cap': 0, 'country': 'United States', 'sector': 'Tech'},
    ]
    out = filter_universe(raw)
    symbols = {r['symbol'] for r in out}
    assert symbols == {'AAPL'}
```

Run: `python -m pytest tests/test_us_universe.py -q`
Expected: PASS(5 passed)

- [ ] **Step 6: Commit**

```bash
git add src/data/us_universe.py tests/test_us_universe.py
git commit -m "feat(us): nasdaq 스크리너 기반 미국 유니버스 소스 추가"
```

---

## Task 2: 일봉·현재가 소스 (`src/data/us_ohlcv.py`)

**Files:**
- Create: `src/data/us_ohlcv.py`
- Test: `tests/test_us_ohlcv.py`

**Interfaces:**
- Consumes: 없음(순수 데이터 소스, Task 1과 독립)
- Produces:
  - `fetch_daily_ohlcv(symbol: str, range_: str = '1y') -> list[dict]` — 오래된→최신 순
    `{'date': 'YYYYMMDD', 'open': float, 'high': float, 'low': float, 'close': float, 'volume': float}`.
    `close`가 None인 날짜는 건너뛴다(공휴일/결측). 실패 시 예외를 올린다.
  - `fetch_current_quote(symbol: str) -> dict | None` — `{'price': float, 'volume': float}`.
    실패하거나 `regularMarketPrice`가 없으면 `None`("측정 불가", 0 폴백 금지).

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_us_ohlcv.py
from unittest import mock

from src.data.us_ohlcv import fetch_daily_ohlcv, fetch_current_quote

DAILY_RESPONSE = {
    "chart": {
        "result": [{
            "timestamp": [1700000000, 1700086400, 1700172800],
            "indicators": {
                "quote": [{
                    "open": [100.0, 101.5, None],
                    "high": [102.0, 103.0, None],
                    "low": [99.0, 100.5, None],
                    "close": [101.0, 102.5, None],
                    "volume": [1000000, 1200000, None],
                }]
            },
            "meta": {"regularMarketPrice": 103.4, "regularMarketVolume": 900000},
        }]
    }
}


def test_fetch_daily_ohlcv_skips_none_close():
    with mock.patch('src.data.us_ohlcv.requests.get') as m:
        m.return_value.raise_for_status = lambda: None
        m.return_value.json.return_value = DAILY_RESPONSE
        bars = fetch_daily_ohlcv('AAPL')
    assert len(bars) == 2
    assert bars[0]['close'] == 101.0
    assert bars[-1]['close'] == 102.5
    assert bars[0]['date'] < bars[-1]['date']


def test_fetch_current_quote_reads_meta():
    with mock.patch('src.data.us_ohlcv.requests.get') as m:
        m.return_value.raise_for_status = lambda: None
        m.return_value.json.return_value = DAILY_RESPONSE
        q = fetch_current_quote('AAPL')
    assert q == {'price': 103.4, 'volume': 900000}


def test_fetch_current_quote_returns_none_when_price_missing():
    resp = {"chart": {"result": [{"meta": {}}]}}
    with mock.patch('src.data.us_ohlcv.requests.get') as m:
        m.return_value.raise_for_status = lambda: None
        m.return_value.json.return_value = resp
        assert fetch_current_quote('AAPL') is None


def test_fetch_current_quote_returns_none_on_exception():
    with mock.patch('src.data.us_ohlcv.requests.get', side_effect=Exception('boom')):
        assert fetch_current_quote('AAPL') is None
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_us_ohlcv.py -q`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# src/data/us_ohlcv.py
"""Yahoo Finance 비공식 chart API — 일봉과 현재가.

scripts/fetch_us_market.py가 지수 4개로 이미 키 없이 안정 작동을 확인한
같은 엔드포인트다. 여기서는 종목 단위로 OHLCV 전체(그 스크립트는 종가만)와
현재가(meta.regularMarketPrice)를 뽑는다.

SLA가 없는 비공식 API라 응답 형식이 바뀌거나 IP가 막힐 수 있다 — 실패는
예외/None으로 드러내고 0으로 지어내지 않는다.
"""
import datetime as dt

import requests

CHART_URL = 'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
HEADERS = {'User-Agent': 'Mozilla/5.0'}

_RANGE_TO_PARAMS = {
    '1y': {'range': '1y', 'interval': '1d'},
    '1d': {'range': '1d', 'interval': '1m'},
}


def _get_chart(symbol: str, range_: str) -> dict:
    params = dict(_RANGE_TO_PARAMS.get(range_, {'range': range_, 'interval': '1d'}))
    r = requests.get(CHART_URL.format(symbol=symbol), params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()['chart']['result'][0]


def fetch_daily_ohlcv(symbol: str, range_: str = '1y') -> list[dict]:
    """일봉 OHLCV. close가 없는 날짜(휴장·결측)는 건너뛴다. 실패 시 예외."""
    res = _get_chart(symbol, range_)
    timestamps = res.get('timestamp') or []
    quote = (res.get('indicators') or {}).get('quote', [{}])[0]
    opens = quote.get('open') or []
    highs = quote.get('high') or []
    lows = quote.get('low') or []
    closes = quote.get('close') or []
    volumes = quote.get('volume') or []

    out = []
    for i, ts in enumerate(timestamps):
        close = closes[i] if i < len(closes) else None
        if close is None:
            continue
        date_str = dt.datetime.utcfromtimestamp(ts).strftime('%Y%m%d')
        out.append({
            'date': date_str,
            'open': opens[i] if i < len(opens) else None,
            'high': highs[i] if i < len(highs) else None,
            'low': lows[i] if i < len(lows) else None,
            'close': close,
            'volume': volumes[i] if i < len(volumes) else None,
        })
    return out


def fetch_current_quote(symbol: str) -> dict | None:
    """실시간에 가까운 현재가·거래량. 실패·결손이면 None(측정 불가)."""
    try:
        res = _get_chart(symbol, '1d')
    except Exception:
        return None
    meta = res.get('meta') or {}
    price = meta.get('regularMarketPrice')
    if price is None:
        return None
    return {'price': float(price), 'volume': float(meta.get('regularMarketVolume') or 0)}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_us_ohlcv.py -q`
Expected: PASS(4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/data/us_ohlcv.py tests/test_us_ohlcv.py
git commit -m "feat(us): Yahoo Finance 일봉·현재가 소스 추가"
```

---

## Task 3: 펀더멘털 소스 (`src/data/us_fundamentals.py`)

**Files:**
- Create: `src/data/us_fundamentals.py`
- Test: `tests/test_us_fundamentals.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `fetch_cik_map() -> dict[str, str]` — `{'AAPL': '0000320193', ...}`(10자리 zero-padded).
  - `fetch_eps_revenue_growth(cik: str) -> dict` — `{'eps_growth_yoy': float | None, 'revenue_growth_yoy': float | None}`.
    태그가 없거나 같은 분기 전년동기 값이 없으면 해당 필드는 `None`.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_us_fundamentals.py
from unittest import mock

from src.data.us_fundamentals import fetch_cik_map, fetch_eps_revenue_growth

TICKERS_RESPONSE = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1318605, "ticker": "TSLA", "title": "Tesla, Inc."},
}

EPS_RESPONSE = {
    "units": {
        "USD/shares": [
            # 전년 동기 분기(약 91일 duration)
            {"start": "2023-07-02", "end": "2023-09-30", "val": 1.46, "form": "10-Q"},
            # 당기 분기(같은 길이)
            {"start": "2024-07-01", "end": "2024-09-28", "val": 1.64, "form": "10-Q"},
            # 연간 누적치(제외 대상 — duration이 훨씬 길다)
            {"start": "2023-10-01", "end": "2024-09-28", "val": 6.11, "form": "10-K"},
        ]
    }
}

REVENUE_MISSING = {}  # 404로 시뮬레이션


def _resp(json_body, status=200):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = json_body
    if status == 200:
        r.raise_for_status = lambda: None
    else:
        r.raise_for_status = mock.Mock(side_effect=Exception('404'))
    return r


def test_fetch_cik_map_zero_pads():
    with mock.patch('src.data.us_fundamentals.requests.get') as m:
        m.return_value = _resp(TICKERS_RESPONSE)
        out = fetch_cik_map()
    assert out['AAPL'] == '0000320193'
    assert out['TSLA'] == '0001318605'


def test_fetch_eps_revenue_growth_computes_yoy():
    def side_effect(url, *a, **kw):
        if 'EarningsPerShareDiluted' in url:
            return _resp(EPS_RESPONSE)
        return _resp(REVENUE_MISSING, status=404)

    with mock.patch('src.data.us_fundamentals.requests.get', side_effect=side_effect):
        out = fetch_eps_revenue_growth('0000320193')
    # (1.64 - 1.46) / 1.46 * 100
    assert round(out['eps_growth_yoy'], 2) == 12.33
    assert out['revenue_growth_yoy'] is None  # 모든 매출 태그가 404


def test_fetch_eps_revenue_growth_no_prior_year_match_is_none():
    only_current = {"units": {"USD/shares": [
        {"start": "2024-07-01", "end": "2024-09-28", "val": 1.64, "form": "10-Q"},
    ]}}
    with mock.patch('src.data.us_fundamentals.requests.get') as m:
        m.return_value = _resp(only_current)
        out = fetch_eps_revenue_growth('0000320193')
    assert out['eps_growth_yoy'] is None
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_us_fundamentals.py -q`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# src/data/us_fundamentals.py
"""SEC EDGAR XBRL — EPS·매출 YoY 성장률(SEPA 실적 가속 필터용).

키 불필요, 완전 무료. User-Agent에 연락 가능한 문자열을 넣는 것이 SEC 정책이다.

EDGAR의 분기 facts에는 같은 종료일(end)에 대해 "이번 분기"와 "연초부터 누적"
값이 섞여 나온다 — 둘 다 같은 태그를 쓴다. 진짜 분기 값만 골라내려면 duration
(end - start)이 순수 1개 분기 길이(약 80~100일)인 항목만 남겨야 한다. 이 필터
없이 최신값만 집으면 절반의 확률로 연간 누적치를 "이번 분기 EPS"로 잘못 읽는다.
"""
import datetime as dt

import requests

TICKERS_URL = 'https://www.sec.gov/files/company_tickers.json'
CONCEPT_URL = 'https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json'
HEADERS = {'User-Agent': 'StockBot research contact@example.com'}

REVENUE_TAGS = [
    'Revenues',
    'RevenueFromContractWithCustomerExcludingAssessedTax',
    'SalesRevenueNet',
]

_MIN_QUARTER_DAYS = 80
_MAX_QUARTER_DAYS = 100


def fetch_cik_map() -> dict[str, str]:
    """ticker(대문자) → 10자리 zero-padded CIK."""
    r = requests.get(TICKERS_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    body = r.json()
    out = {}
    for entry in body.values():
        ticker = str(entry.get('ticker', '')).upper()
        cik = entry.get('cik_str')
        if ticker and cik is not None:
            out[ticker] = str(cik).zfill(10)
    return out


def _quarterly_entries(units: dict) -> list[dict]:
    """분기 길이(80~100일)인 항목만. 연간 누적·반기 누적을 제외한다."""
    entries = units.get('USD/shares') or units.get('USD') or []
    out = []
    for e in entries:
        try:
            start = dt.date.fromisoformat(e['start'])
            end = dt.date.fromisoformat(e['end'])
        except (KeyError, ValueError):
            continue
        days = (end - start).days
        if _MIN_QUARTER_DAYS <= days <= _MAX_QUARTER_DAYS:
            out.append({'end': end, 'val': e.get('val')})
    return sorted(out, key=lambda x: x['end'])


def _latest_yoy(entries: list[dict]) -> float | None:
    """가장 최근 분기 값과, 그로부터 약 1년 전(345~385일) 분기 값의 YoY."""
    if not entries:
        return None
    latest = entries[-1]
    target_start = latest['end'] - dt.timedelta(days=385)
    target_end = latest['end'] - dt.timedelta(days=345)
    prior = next((e for e in entries if target_start <= e['end'] <= target_end), None)
    if prior is None or not prior['val']:
        return None
    return (latest['val'] - prior['val']) / abs(prior['val']) * 100.0


def _fetch_concept(cik: str, tag: str) -> dict | None:
    url = CONCEPT_URL.format(cik=cik, tag=tag)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def fetch_eps_revenue_growth(cik: str) -> dict:
    """EPS·매출 YoY(%). 태그를 못 찾거나 전년동기 짝이 없으면 None(측정 불가)."""
    eps_growth = None
    eps_body = _fetch_concept(cik, 'EarningsPerShareDiluted')
    if eps_body:
        eps_growth = _latest_yoy(_quarterly_entries(eps_body.get('units') or {}))

    revenue_growth = None
    for tag in REVENUE_TAGS:
        body = _fetch_concept(cik, tag)
        if not body:
            continue
        revenue_growth = _latest_yoy(_quarterly_entries(body.get('units') or {}))
        if revenue_growth is not None:
            break

    return {'eps_growth_yoy': eps_growth, 'revenue_growth_yoy': revenue_growth}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_us_fundamentals.py -q`
Expected: PASS(3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/data/us_fundamentals.py tests/test_us_fundamentals.py
git commit -m "feat(us): SEC EDGAR 기반 EPS·매출 YoY 소스 추가"
```

---

## Task 4: `USBaseSimulator` (KRW 전제 흡수)

**Files:**
- Create: `src/strategy/simulators/us_base_simulator.py`
- Test: `tests/test_us_base_simulator.py`

**Interfaces:**
- Consumes: `src.strategy.simulators.base_simulator.BaseSimulator`
- Produces: `USBaseSimulator(BaseSimulator)` — US 심 6개가 전부 이 클래스를 상속한다.
  `BUY_FEE_RATE = SELL_FEE_RATE = SELL_TAX_RATE = 0.0`, `log_trade()`가 가격을
  소수점 2자리까지 보존.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_us_base_simulator.py
import csv
import os
import tempfile

from src.strategy.simulators.us_base_simulator import USBaseSimulator


class _Dummy(USBaseSimulator):
    def __init__(self, data_dir, initial_cash=20000):
        self.name = 'UsDummy'
        self.initial_cash = initial_cash
        self.data_dir = data_dir
        self.state_file = os.path.join(data_dir, 'sim_usdummy_state.json')
        self.log_file = os.path.join(data_dir, 'sim_usdummy_log.json')
        self.csv_file = os.path.join(data_dir, 'trade_history_sim_usdummy.csv')
        self.load_state()


def test_fee_rates_are_zero():
    with tempfile.TemporaryDirectory() as d:
        sim = _Dummy(d)
    assert sim.BUY_FEE_RATE == 0.0
    assert sim.SELL_FEE_RATE == 0.0
    assert sim.SELL_TAX_RATE == 0.0


def test_log_trade_preserves_cents():
    with tempfile.TemporaryDirectory() as d:
        sim = _Dummy(d)
        sim.buy('AAPL', 'Apple', 45.67, 10, reason='test')
        with open(sim.csv_file, encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
    assert rows[0]['price'] == '45.67'
    assert rows[0]['total_amount'] == '456.70'


def test_buy_charges_no_fee():
    with tempfile.TemporaryDirectory() as d:
        sim = _Dummy(d, initial_cash=1000.0)
        sim.buy('AAPL', 'Apple', 45.67, 10, reason='test')
    # 수수료 0이므로 cash 차감분은 정확히 qty*price
    assert round(sim.state['cash'], 2) == round(1000.0 - 456.7, 2)
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_us_base_simulator.py -q`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# src/strategy/simulators/us_base_simulator.py
"""BaseSimulator의 KRW 전제 2개를 흡수하는 공용 US 부모 클래스.

US 심 6개가 전부 이 클래스를 상속한다(개별 심마다 중복 오버라이드하지 않는다).

1. 수수료·세금 — BUY_FEE_RATE/SELL_FEE_RATE/SELL_TAX_RATE는 src/trade/fees.py의
   한국 위탁수수료·증권거래세다. 미국은 리테일 브로커 대부분이 커미션 프리이고
   SEC 초소액 수수료(주당 몇 센트 미만)는 페이퍼 심의 손익 순수성을 지키려고
   반영하지 않는다 — 0으로 둔다.
2. 가격 절사 — BaseSimulator.log_trade()가 CSV에 가격을 int(price)로 적는다.
   원화는 정수 단위라 문제없지만 달러는 $45.67 같은 소수점이 의미를 갖는다.
   여기서 log_trade를 오버라이드해 소수점 2자리를 보존한다.
"""
from .base_simulator import BaseSimulator, ensure_csv_header, get_kst_now, CSV_HEADER
import csv


class USBaseSimulator(BaseSimulator):
    BUY_FEE_RATE = 0.0
    SELL_FEE_RATE = 0.0
    SELL_TAX_RATE = 0.0

    def log_trade(self, action, code, name, quantity, price, reason, roi_pct=None, roi_amount=None):
        timestamp = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
        ensure_csv_header(self.csv_file)
        with open(self.csv_file, 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                timestamp, f"{name}({code})", action,
                f"{price:.2f}", quantity, f"{quantity * price:.2f}", reason,
                '' if roi_pct is None else f"{roi_pct:+.2f}",
                '' if roi_amount is None else f"{roi_amount:.2f}",
            ])
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_us_base_simulator.py -q`
Expected: PASS(3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/strategy/simulators/us_base_simulator.py tests/test_us_base_simulator.py
git commit -m "feat(us): KRW 수수료·정수가격 절사를 흡수하는 USBaseSimulator 추가"
```

---

## Task 5: US Sim1 — 미너비니 전략 로직

**Files:**
- Create: `src/strategy/simulators/us_sim1_minervini.py`
- Test: `tests/test_us_sim1_minervini.py`

**Interfaces:**
- Consumes:
  - `USBaseSimulator`(Task 4)
  - 워치리스트 엔트리 shape(Task 8이 생성): `{'name': str, 'pivot_price': float, 'ma50': float}`
- Produces:
  - `build_watchlist_entry(stock: dict) -> dict | None` — `stock`은
    `{'symbol', 'price', 'daily_closes'(오늘 미포함), 'w52_hgpr', 'w52_lwpr', 'eps_growth_yoy', 'revenue_growth_yoy'}`.
  - `save_watchlist(entries: dict[str, dict], date_str: str) -> None`
  - `load_watchlist(date_str: str) -> dict[str, dict]`
  - `decide_us_minervini(view: dict, candidates: list[dict], current_prices: dict[str, float]) -> list[dict]`
    — Order 리스트(`{'action','code','name'?,'price','quantity','reason','cooldown'?}`).
  - `class USMinerviniSimulator(USBaseSimulator)` — `get_universe()`/`run()`.
  - 상수: `MAX_HOLDINGS=5`, `POSITION_WEIGHT=0.19`, `MIN_AMOUNT=10_000_000`(USD 일일
    거래대금 최소 문턱 — 국내 Sim11의 KRW 10억 문턱을 미국 대형주 유동성 기준으로
    재조정한 근사치), `STOP_PCT=-7.5`, `MA_EXIT_WINDOW=50`,
    `MIN_ABOVE_52W_LOW_PCT=30.0`, `MAX_BELOW_52W_HIGH_PCT=25.0`,
    `MA200_TREND_LOOKBACK=20`, `MIN_EPS_GROWTH_YOY=20.0`, `MIN_REVENUE_GROWTH_YOY=15.0`,
    `CONTRACTION_WINDOW=10`, `PIVOT_WINDOW=20`, `CONTRACTION_RATIO=0.7`
    (국내 Sim11과 전부 동일한 값 — MIN_AMOUNT만 다르다).

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_us_sim1_minervini.py
import json
import os
import tempfile
from unittest import mock

from src.strategy.simulators import us_sim1_minervini as m


def _uptrend_closes(n=230, start=50.0, step=0.15):
    return [round(start + i * step, 2) for i in range(n)]


def test_trend_template_passes_clean_uptrend():
    closes = _uptrend_closes()
    price = closes[-1] + 1
    ok = m._trend_template_ok(price, closes, w52_hgpr=price, w52_lwpr=closes[0])
    assert ok is True


def test_trend_template_fails_short_history():
    closes = _uptrend_closes(n=50)
    assert m._trend_template_ok(closes[-1] + 1, closes, closes[-1], closes[0]) is False


def test_vcp_contracting_true_when_recent_range_narrower():
    prior = [100, 110, 90, 105, 95, 108, 92, 107, 93, 106]
    recent = [100, 101, 99, 100.5, 99.5, 100.2, 99.8, 100.1, 99.9, 100]
    assert m._vcp_contracting(prior + recent) is True


def test_build_watchlist_entry_requires_earnings_filter():
    closes = _uptrend_closes()
    stock = {
        'symbol': 'AAPL', 'price': closes[-1] + 1, 'daily_closes': closes,
        'w52_hgpr': closes[-1] + 1, 'w52_lwpr': closes[0],
        'eps_growth_yoy': 10.0,  # MIN_EPS_GROWTH_YOY(20) 미달
        'revenue_growth_yoy': 20.0,
    }
    assert m.build_watchlist_entry(stock) is None


def test_save_and_load_watchlist_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'WATCHLIST_PATH', str(tmp_path / 'sim_us1_minervini_watchlist.json'))
    entries = {'AAPL': {'name': 'Apple', 'pivot_price': 200.0, 'ma50': 190.0}}
    m.save_watchlist(entries, '20260823')
    assert m.load_watchlist('20260823') == entries
    assert m.load_watchlist('20260824') == {}  # 날짜 불일치는 빈 딕셔너리(fail-closed)


def test_decide_us_minervini_hard_stop_sells():
    view = {'portfolio': {'TSLA': {'avg_price': 200.0}}, 'nav': 20000.0, 'cooldown_codes': {}}
    candidates = []
    current_prices = {'TSLA': 184.0}  # -8%, STOP_PCT(-7.5%) 하회
    orders = m.decide_us_minervini(view, candidates, current_prices)
    assert len(orders) == 1
    assert orders[0]['action'] == 'SELL'
    assert orders[0]['code'] == 'TSLA'


def test_decide_us_minervini_buys_on_pivot_breakout():
    view = {'portfolio': {}, 'nav': 20000.0, 'cooldown_codes': {}}
    candidates = [{'symbol': 'AAPL', 'price': 205.0, 'amount': 50_000_000,
                   'pivot_price': 200.0, 'ma50': 190.0, 'name': 'Apple'}]
    # decide_us_minervini는 candidates에서 'code' 키를 읽는다 — get_universe()가
    # 'symbol'을 'code'로 옮겨 준다(Sim11의 KIS 'code' 관례와 맞춘다).
    candidates[0]['code'] = candidates[0].pop('symbol')
    orders = m.decide_us_minervini(view, candidates, {'AAPL': 205.0})
    assert len(orders) == 1
    assert orders[0]['action'] == 'BUY'
    assert orders[0]['code'] == 'AAPL'
    assert orders[0]['quantity'] == int(20000.0 * 0.19 / 205.0)


def test_us_minervini_simulator_get_universe_reads_todays_watchlist(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'WATCHLIST_PATH', str(tmp_path / 'wl.json'))
    m.save_watchlist({'AAPL': {'name': 'Apple', 'pivot_price': 200.0, 'ma50': 190.0}},
                      m.get_kst_now().strftime('%Y%m%d'))
    with tempfile.TemporaryDirectory() as d:
        sim = m.USMinerviniSimulator.__new__(m.USMinerviniSimulator)
        sim.name = 'Us1Minervini'
        sim.initial_cash = 20000
        sim.data_dir = d
        sim.state_file = os.path.join(d, 'sim_us1minervini_state.json')
        sim.log_file = os.path.join(d, 'sim_us1minervini_log.json')
        sim.csv_file = os.path.join(d, 'trade_history_sim_us1minervini.csv')
        sim.load_state()
        universe = sim.get_universe()
    assert universe == [{'code': 'AAPL', 'name': 'Apple', 'pivot_price': 200.0, 'ma50': 190.0}]
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_us_sim1_minervini.py -q`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# src/strategy/simulators/us_sim1_minervini.py
"""US Sim1 — 미너비니 추세형(SEPA/VCP), 국내 Sim11의 미국 이식.

로직(추세 템플릿·VCP 압축·pivot 돌파·손절·50일선 이탈)은 국내 Sim11
(sim11_minervini.py)과 동일하다 — 통화·데이터 소스만 다르다. 국내 파이프라인
독립 원칙 때문에 sim11_minervini.py를 import하지 않고 그대로 옮겨 적는다.

EOD 배치(scripts/run_eod_sim_us.py)가 추세 템플릿+실적 가속+VCP 압축을 하루
1회 계산해 워치리스트에 남기고, 실제 매수/매도는 장중 루프
(scripts/us_trade_loop.py)가 실시간에 가까운 가격으로 판단한다
(program-trading-parity 원칙 — 국내와 동일하게 룩어헤드를 피한다).
"""
import json
import os

from .us_base_simulator import USBaseSimulator
from .base_simulator import BaseSimulator, get_kst_now

_cooldown_active = BaseSimulator.cooldown_active

MAX_HOLDINGS = 5
POSITION_WEIGHT = 0.19
MIN_AMOUNT = 10_000_000  # 미국 대형주 유동성 기준 일일 거래대금 최소 문턱(USD)

STOP_PCT = -7.5
MA_EXIT_WINDOW = 50

MIN_ABOVE_52W_LOW_PCT = 30.0
MAX_BELOW_52W_HIGH_PCT = 25.0
MA200_TREND_LOOKBACK = 20

MIN_EPS_GROWTH_YOY = 20.0
MIN_REVENUE_GROWTH_YOY = 15.0

CONTRACTION_WINDOW = 10
PIVOT_WINDOW = 20
CONTRACTION_RATIO = 0.7

WATCHLIST_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'data',
    'sim_us1_minervini_watchlist.json')


def _sma(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _trend_template_ok(price: float, closes: list[float],
                       w52_hgpr: float, w52_lwpr: float) -> bool:
    ma50 = _sma(closes, 50)
    ma150 = _sma(closes, 150)
    ma200 = _sma(closes, 200)
    if ma50 is None or ma150 is None or ma200 is None:
        return False
    if len(closes) < 200 + MA200_TREND_LOOKBACK:
        return False
    ma200_prior = _sma(closes[:-MA200_TREND_LOOKBACK], 200)
    if ma200_prior is None:
        return False
    if not (price > ma150 > ma200):
        return False
    if not (ma50 > ma150 and ma50 > ma200):
        return False
    if not (price > ma50):
        return False
    if not (ma200 > ma200_prior):
        return False
    if w52_lwpr <= 0 or w52_hgpr <= 0:
        return False
    if price < w52_lwpr * (1 + MIN_ABOVE_52W_LOW_PCT / 100):
        return False
    if price < w52_hgpr * (1 - MAX_BELOW_52W_HIGH_PCT / 100):
        return False
    return True


def _vcp_contracting(closes: list[float]) -> bool:
    need = CONTRACTION_WINDOW * 2
    if len(closes) < need:
        return False
    recent = closes[-CONTRACTION_WINDOW:]
    prior = closes[-CONTRACTION_WINDOW * 2:-CONTRACTION_WINDOW]
    if recent[-1] <= 0 or prior[-1] <= 0:
        return False
    recent_range = (max(recent) - min(recent)) / recent[-1]
    prior_range = (max(prior) - min(prior)) / prior[-1]
    if prior_range <= 0:
        return False
    return recent_range < prior_range * CONTRACTION_RATIO


def build_watchlist_entry(stock: dict) -> dict | None:
    """stock: {'symbol','price','daily_closes'(오늘 미포함),'w52_hgpr','w52_lwpr',
    'eps_growth_yoy','revenue_growth_yoy'}. 자격 미달이면 None."""
    price = float(stock.get('price', 0) or 0)
    daily_closes = stock.get('daily_closes') or []
    if price <= 0:
        return None

    w52_hgpr = float(stock.get('w52_hgpr', 0) or 0)
    w52_lwpr = float(stock.get('w52_lwpr', 0) or 0)
    if not _trend_template_ok(price, daily_closes, w52_hgpr, w52_lwpr):
        return None

    eps_g = stock.get('eps_growth_yoy')
    rev_g = stock.get('revenue_growth_yoy')
    if eps_g is None or eps_g < MIN_EPS_GROWTH_YOY:
        return None
    if rev_g is None or rev_g < MIN_REVENUE_GROWTH_YOY:
        return None

    closes_through_today = daily_closes + [price]
    if not _vcp_contracting(closes_through_today):
        return None
    ma50 = _sma(closes_through_today, MA_EXIT_WINDOW)
    if ma50 is None:
        return None

    return {
        'name': stock.get('name', stock.get('symbol', '')),
        'pivot_price': max(closes_through_today[-PIVOT_WINDOW:]),
        'ma50': ma50,
    }


def save_watchlist(entries: dict[str, dict], date_str: str) -> None:
    os.makedirs(os.path.dirname(WATCHLIST_PATH), exist_ok=True)
    with open(WATCHLIST_PATH, 'w', encoding='utf-8') as f:
        json.dump({'date': date_str, 'entries': entries}, f, ensure_ascii=False)


def load_watchlist(date_str: str) -> dict[str, dict]:
    """오늘 날짜와 일치할 때만 돌려준다(fail-closed) — 국내 Sim11과 동일 관례."""
    try:
        with open(WATCHLIST_PATH, encoding='utf-8-sig') as f:
            data = json.load(f)
    except Exception:
        return {}
    if not isinstance(data, dict) or data.get('date') != date_str:
        return {}
    entries = data.get('entries')
    return entries if isinstance(entries, dict) else {}


def decide_us_minervini(view, candidates, current_prices):
    """국내 Sim11의 decide_minervini와 동일 로직(통화 무관 순수 함수)."""
    orders = []
    portfolio = view['portfolio']
    sold = set()
    cand_by_code = {s['code']: s for s in candidates if s.get('code')}

    for code in list(portfolio.keys()):
        p = portfolio[code]
        cur = current_prices.get(code, 0)
        avg = p.get('avg_price', 0)
        if cur <= 0 or avg <= 0:
            continue
        pr = (cur - avg) / avg * 100

        if pr <= STOP_PCT:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[US미너비니] 손절 ({pr:+.1f}%)",
                           'cooldown': 3, 'mark_partial': False})
            sold.add(code); continue

        ma50 = (cand_by_code.get(code) or {}).get('ma50')
        if ma50 is not None and cur < ma50:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[US미너비니] {MA_EXIT_WINDOW}일선 이탈 ({ma50:,.2f} 하회, {pr:+.1f}%)",
                           'cooldown': 3, 'mark_partial': False})
            sold.add(code); continue

    target_amount = view['nav'] * POSITION_WEIGHT
    held = len([c for c in portfolio if c not in sold])
    for stock in candidates:
        if held >= MAX_HOLDINGS:
            break
        code = stock.get('code')
        if not code or code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            continue

        price = float(stock.get('price', 0) or 0)
        amount = float(stock.get('amount', 0) or 0)
        pivot = stock.get('pivot_price')
        if price <= 0 or pivot is None or amount < MIN_AMOUNT:
            continue
        if price <= pivot:
            continue

        qty = int(target_amount / price)
        if qty > 0:
            orders.append({'action': 'BUY', 'code': code, 'name': stock.get('name', code),
                           'price': price, 'quantity': qty, 'cooldown': None,
                           'reason': f"[US미너비니] 실시간 pivot 돌파 (${pivot:,.2f} 상회)"})
            held += 1
    return orders


class USMinerviniSimulator(USBaseSimulator):
    """[US Sim1] 미너비니 추세형 — 국내 Sim11 이식. 상세 배경은 위 모듈 docstring."""

    def __init__(self, initial_cash=20000):
        super().__init__("Us1Minervini", initial_cash)

    def get_universe(self):
        today = get_kst_now().strftime('%Y%m%d')
        entries = load_watchlist(today)
        return [
            {'code': code, 'name': e.get('name', code),
             'pivot_price': e.get('pivot_price'), 'ma50': e.get('ma50')}
            for code, e in entries.items()
        ]

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        orders = decide_us_minervini(self._view(current_prices), candidates, current_prices)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_us_sim1_minervini.py -q`
Expected: PASS(8 passed)

- [ ] **Step 5: Commit**

```bash
git add src/strategy/simulators/us_sim1_minervini.py tests/test_us_sim1_minervini.py
git commit -m "feat(us): US Sim1 미너비니 추세형 전략 로직 추가"
```

---

## Task 6: 독립 매니페스트 + 레지스트리

**Files:**
- Create: `src/strategy/us_strategy_manifest.yaml`
- Create: `src/strategy/us_registry.py`
- Test: `tests/test_us_registry.py`

**Interfaces:**
- Consumes: Task 5의 `USMinerviniSimulator`
- Produces:
  - `get_us_sim_registry() -> list[dict]` — 항목: `id, ui_key, label, short_desc, chart_group,
    color, state_file, csv_file, tradeable, currency`.
  - `get_active_us_simulators() -> list` — 인스턴스 목록(현재 1개).
  - `get_us_simulator_by_id(sim_id: str) -> object | None`

- [ ] **Step 1: 매니페스트 작성**

```yaml
# src/strategy/us_strategy_manifest.yaml
# ================================================================
# 미국 주식 페이퍼 심 등록부 — src/strategy/strategy_manifest.yaml(국내)과
# 완전히 분리된 파일이다. 이유: src/pipeline/workers/trade_engine.py의
# _run_simulators()가 국내 매니페스트의 active:true 전체를 KIS 실시간가·
# 국내 후보로 돌린다 — US 심을 거기 얹으면 60초 국내 루프가 매 틱마다 US 심에도
# 원화 후보/시세를 먹이려 시도해 조용히 망가진다.
#
# [새 US 심 추가 방법]
#   1. src/strategy/simulators/us_simN_xxx.py 작성(USBaseSimulator 상속)
#   2. 이 파일 simulators 항목에 블록 추가
#   3. python scripts/gen_us_sim_registry.py 실행 → src/lib/us-sim-registry.generated.ts 갱신
# ================================================================

simulators:
  - id: "us_sim1_minervini"
    module: "src.strategy.simulators.us_sim1_minervini"
    class: "USMinerviniSimulator"
    description: "US Sim1 미너비니 추세형 — 추세 템플릿+실적 가속(EPS·매출)+VCP 압축 돌파"
    state_file: "sim_us1minervini_state.json"
    csv_file: "trade_history_sim_us1minervini.csv"
    label: "US 미너비니 추세형 (US Sim 1)"
    display_order: 10
    ui_key: "us_sim1"
    short_desc: "추세 템플릿 + 실적 가속(EPS·매출) + VCP 압축 돌파"
    chart_group: 1
    color: "blue"
    currency: "USD"
    active: true
    tradeable: false  # 페이퍼 관찰 단계
```

- [ ] **Step 2: 실패 테스트 작성**

```python
# tests/test_us_registry.py
from src.strategy.us_registry import get_us_sim_registry, get_active_us_simulators, get_us_simulator_by_id


def test_get_us_sim_registry_has_sim1():
    reg = get_us_sim_registry()
    assert len(reg) == 1
    entry = reg[0]
    assert entry['id'] == 'us_sim1_minervini'
    assert entry['currency'] == 'USD'
    assert entry['state_file'] == 'sim_us1minervini_state.json'


def test_get_active_us_simulators_instantiates():
    sims = get_active_us_simulators()
    assert len(sims) == 1
    assert sims[0].name == 'Us1Minervini'


def test_get_us_simulator_by_id_unknown_returns_none():
    assert get_us_simulator_by_id('nope') is None


def test_get_us_simulator_by_id_known():
    sim = get_us_simulator_by_id('us_sim1_minervini')
    assert sim is not None
    assert sim.name == 'Us1Minervini'
```

- [ ] **Step 3: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_us_registry.py -q`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 4: 구현**

```python
# src/strategy/us_registry.py
"""us_strategy_manifest.yaml 전용 레지스트리. src/strategy/registry.py(국내)와
완전히 분리돼 있다 — 서로 import하지 않는다."""
import importlib
import os

import yaml

MANIFEST_PATH = os.path.join(os.path.dirname(__file__), 'us_strategy_manifest.yaml')


def _load_manifest() -> dict:
    with open(MANIFEST_PATH, encoding='utf-8') as f:
        return yaml.safe_load(f)


def _load_class(module_path: str, class_name: str):
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def get_us_sim_registry() -> list[dict]:
    out = []
    for s in _load_manifest().get('simulators', []):
        if not s.get('active', True):
            continue
        out.append({
            'id': s['id'], 'ui_key': s['ui_key'], 'label': s['label'],
            'short_desc': s['short_desc'], 'chart_group': s['chart_group'],
            'color': s['color'], 'state_file': s['state_file'], 'csv_file': s['csv_file'],
            'tradeable': bool(s.get('tradeable', False)), 'currency': s.get('currency', 'USD'),
            'display_order': s.get('display_order', 9999),
        })
    return sorted(out, key=lambda x: x['display_order'])


def get_active_us_simulators() -> list:
    sims = []
    for s in _load_manifest().get('simulators', []):
        if not s.get('active', True):
            continue
        cls = _load_class(s['module'], s['class'])
        sims.append(cls())
    return sims


def get_us_simulator_by_id(sim_id: str):
    for s in _load_manifest().get('simulators', []):
        if s['id'] == sim_id and s.get('active', True):
            cls = _load_class(s['module'], s['class'])
            return cls()
    return None
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `python -m pytest tests/test_us_registry.py -q`
Expected: PASS(4 passed)

- [ ] **Step 6: Commit**

```bash
git add src/strategy/us_strategy_manifest.yaml src/strategy/us_registry.py tests/test_us_registry.py
git commit -m "feat(us): 국내와 분리된 US 심 매니페스트·레지스트리 추가"
```

---

## Task 7: TS 레지스트리 생성기

**Files:**
- Create: `scripts/gen_us_sim_registry.py`
- Create (생성됨, 커밋 대상): `src/lib/us-sim-registry.generated.ts`
- Test: `src/lib/us-sim-registry.test.ts`

**Interfaces:**
- Consumes: Task 6의 `get_us_sim_registry()`
- Produces: `US_SIM_REGISTRY: USSimRegistryEntry[]`(TS export, `currency` 필드 포함).

- [ ] **Step 1: 생성기 작성**

```python
# scripts/gen_us_sim_registry.py
"""us_strategy_manifest.yaml → src/lib/us-sim-registry.generated.ts.

scripts/gen_sim_registry.py(국내)와 같은 이유로 존재한다 — TS는 'use client'
컴포넌트라 fs로 YAML을 못 읽는다. 국내 생성기·생성 파일은 건드리지 않는다.

    python scripts/gen_us_sim_registry.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.us_registry import get_us_sim_registry  # noqa: E402

OUT_PATH = os.path.join(os.path.dirname(__file__), '..', 'src', 'lib', 'us-sim-registry.generated.ts')

HEADER = """// 이 파일은 생성됩니다. 직접 고치지 마세요.
// 원천: src/strategy/us_strategy_manifest.yaml
// 생성: python scripts/gen_us_sim_registry.py

export interface USSimRegistryEntry {
  id: string;
  uiKey: string;
  label: string;
  shortDesc: string;
  color: string;
  chartGroup: number;
  stateFile: string;
  csvFile: string;
  tradeable: boolean;
  currency: string;
}
"""


def _ts(value) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace('\\', '\\\\').replace("'", "\\'") + "'"


def build() -> str:
    reg = get_us_sim_registry()
    lines = [HEADER, 'export const US_SIM_REGISTRY: USSimRegistryEntry[] = [']
    for s in reg:
        fields = [
            ('id', s['id']), ('uiKey', s['ui_key']), ('label', s['label']),
            ('shortDesc', s['short_desc']), ('color', s['color']),
            ('chartGroup', s['chart_group']), ('stateFile', s['state_file']),
            ('csvFile', s['csv_file']), ('tradeable', s['tradeable']),
            ('currency', s['currency']),
        ]
        lines.append('  { ' + ', '.join(f'{k}: {_ts(v)}' for k, v in fields) + ' },')
    lines.append('];')
    return '\n'.join(lines)


if __name__ == '__main__':
    content = build()
    with open(OUT_PATH, 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)
    print(f'[gen_us_sim_registry] {os.path.relpath(OUT_PATH)} 갱신 — US 심 {len(get_us_sim_registry())}개')
```

- [ ] **Step 2: 생성기 실행**

Run: `PYTHONPATH=. python scripts/gen_us_sim_registry.py`
Expected: `src/lib/us-sim-registry.generated.ts` 생성, `US 심 1개` 출력

- [ ] **Step 3: 생성 결과 확인 테스트 작성**

```typescript
// src/lib/us-sim-registry.test.ts
import { test } from 'node:test';
import assert from 'node:assert';
import { US_SIM_REGISTRY } from './us-sim-registry.generated.ts';

test('US_SIM_REGISTRY has us_sim1 with USD currency', () => {
  assert.equal(US_SIM_REGISTRY.length, 1);
  const s = US_SIM_REGISTRY[0];
  assert.equal(s.id, 'us_sim1_minervini');
  assert.equal(s.uiKey, 'us_sim1');
  assert.equal(s.currency, 'USD');
  assert.equal(s.stateFile, 'sim_us1minervini_state.json');
  assert.equal(s.tradeable, false);
});
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `node --test "src/lib/us-sim-registry.test.ts"`
Expected: PASS(1 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/gen_us_sim_registry.py src/lib/us-sim-registry.generated.ts src/lib/us-sim-registry.test.ts
git commit -m "feat(us): US 심 레지스트리 TS 생성기 추가"
```

---

## Task 8: EOD 워치리스트 배치

**Files:**
- Create: `scripts/run_eod_sim_us.py`
- Test: `tests/test_run_eod_sim_us.py`

**Interfaces:**
- Consumes: `fetch_us_universe`/`filter_universe`(Task 1), `fetch_daily_ohlcv`(Task 2),
  `fetch_cik_map`/`fetch_eps_revenue_growth`(Task 3), `build_watchlist_entry`/`save_watchlist`
  (Task 5).
- Produces: `build_watchlist_for_universe(universe: list[dict], cik_map: dict[str,str]) -> dict[str, dict]`
  — 순수 오케스트레이션 함수(네트워크 호출은 인자로 주입된 함수를 통해서만 — 테스트에서
  모킹 가능). `main()`이 실제 배선.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_run_eod_sim_us.py
from unittest import mock

from scripts.run_eod_sim_us import build_watchlist_for_universe


def _uptrend_closes(n=230, start=50.0, step=0.15):
    return [round(start + i * step, 2) for i in range(n)]


def test_build_watchlist_skips_short_history_without_fundamentals_call():
    universe = [{'symbol': 'NEWCO', 'name': 'New Co', 'market_cap': 1e9}]
    fetch_ohlcv = mock.Mock(return_value=[{'close': 10.0, 'high': 10.0, 'low': 9.0}] * 30)
    fetch_fund = mock.Mock()
    out = build_watchlist_for_universe(
        universe, cik_map={'NEWCO': '0000000001'},
        fetch_ohlcv=fetch_ohlcv, fetch_fundamentals=fetch_fund)
    assert out == {}
    fetch_fund.assert_not_called()  # 추세 템플릿 탈락 종목엔 EDGAR 콜을 안 낸다


def test_build_watchlist_includes_symbol_passing_all_filters():
    closes = _uptrend_closes()
    bars = [{'close': c, 'high': c, 'low': c} for c in closes]
    universe = [{'symbol': 'AAPL', 'name': 'Apple Inc.', 'market_cap': 3e12}]
    fetch_ohlcv = mock.Mock(return_value=bars)
    fetch_fund = mock.Mock(return_value={'eps_growth_yoy': 25.0, 'revenue_growth_yoy': 20.0})
    out = build_watchlist_for_universe(
        universe, cik_map={'AAPL': '0000320193'},
        fetch_ohlcv=fetch_ohlcv, fetch_fundamentals=fetch_fund)
    assert 'AAPL' in out
    fetch_fund.assert_called_once_with('0000320193')


def test_build_watchlist_skips_symbol_without_cik():
    closes = _uptrend_closes()
    bars = [{'close': c, 'high': c, 'low': c} for c in closes]
    universe = [{'symbol': 'NOCIK', 'name': 'No Cik', 'market_cap': 1e9}]
    fetch_ohlcv = mock.Mock(return_value=bars)
    fetch_fund = mock.Mock()
    out = build_watchlist_for_universe(
        universe, cik_map={}, fetch_ohlcv=fetch_ohlcv, fetch_fundamentals=fetch_fund)
    assert out == {}
    fetch_fund.assert_not_called()
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_run_eod_sim_us.py -q`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# scripts/run_eod_sim_us.py
"""US Sim1 EOD 워치리스트 배치 — 하루 1회, 미국장 마감 이후 실행.

무거운 계산(추세 템플릿·VCP 압축·실적 가속)을 여기서 끝내고
data/sim_us1_minervini_watchlist.json에 남긴다. 장중 루프(us_trade_loop.py)는
이 파일만 읽고 실시간가로 pivot 돌파만 본다(program-trading-parity 원칙).

트렌드 템플릿을 먼저 통과한 종목에만 SEC EDGAR를 조회한다 — 유니버스 전체에
펀더멘털을 조회하면 EDGAR 콜이 수백~수천 건이 된다.

    PYTHONPATH=. python scripts/run_eod_sim_us.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data.us_universe import fetch_us_universe, filter_universe, save_universe  # noqa: E402
from src.data.us_ohlcv import fetch_daily_ohlcv  # noqa: E402
from src.data.us_fundamentals import fetch_cik_map, fetch_eps_revenue_growth  # noqa: E402
from src.strategy.simulators.us_sim1_minervini import (  # noqa: E402
    build_watchlist_entry, save_watchlist, _trend_template_ok,
)
from src.strategy.simulators.base_simulator import get_kst_now  # noqa: E402

MIN_HISTORY_DAYS = 220


def build_watchlist_for_universe(universe, cik_map, fetch_ohlcv, fetch_fundamentals):
    """오케스트레이션. 네트워크 함수는 주입 — 테스트에서 모킹한다."""
    out = {}
    for row in universe:
        symbol = row['symbol']
        bars = fetch_ohlcv(symbol)
        if len(bars) < MIN_HISTORY_DAYS:
            continue
        closes = [b['close'] for b in bars]
        price = closes[-1]
        daily_closes = closes[:-1]
        w52_window = bars[-252:] if len(bars) >= 252 else bars
        w52_hgpr = max(b['high'] for b in w52_window)
        w52_lwpr = min(b['low'] for b in w52_window)

        if not _trend_template_ok(price, daily_closes, w52_hgpr, w52_lwpr):
            continue

        cik = cik_map.get(symbol)
        if not cik:
            continue
        fund = fetch_fundamentals(cik)

        entry = build_watchlist_entry({
            'symbol': symbol, 'name': row.get('name', symbol), 'price': price,
            'daily_closes': daily_closes, 'w52_hgpr': w52_hgpr, 'w52_lwpr': w52_lwpr,
            'eps_growth_yoy': fund.get('eps_growth_yoy'),
            'revenue_growth_yoy': fund.get('revenue_growth_yoy'),
        })
        if entry:
            out[symbol] = entry
    return out


def main():
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    universe_raw = fetch_us_universe(limit=1000)
    universe = filter_universe(universe_raw)
    save_universe(universe, os.path.join(data_dir, 'us_universe.json'))
    print(f'[EOD-US] 유니버스 {len(universe)}종목')

    cik_map = fetch_cik_map()
    watchlist = build_watchlist_for_universe(
        universe, cik_map, fetch_daily_ohlcv, fetch_eps_revenue_growth)
    today = get_kst_now().strftime('%Y%m%d')
    save_watchlist(watchlist, today)
    print(f'[EOD-US] 워치리스트 {len(watchlist)}종목 저장 (날짜 {today})')


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_run_eod_sim_us.py -q`
Expected: PASS(3 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/run_eod_sim_us.py tests/test_run_eod_sim_us.py
git commit -m "feat(us): US Sim1 EOD 워치리스트 배치 스크립트 추가"
```

---

## Task 9: 장중 페이퍼 체결 루프

**Files:**
- Create: `scripts/us_trade_loop.py`
- Test: `tests/test_us_trade_loop.py`

**Interfaces:**
- Consumes: `fetch_current_quote`(Task 2), `USMinerviniSimulator`(Task 5),
  `get_active_us_simulators`(Task 6).
- Produces:
  - `is_us_market_open(now_utc=None) -> bool` — `zoneinfo`(`America/New_York`) 기준
    평일 09:30~16:00 ET(서머타임 자동 반영). 주말은 False.
  - `run_cycle(simulators, fetch_quote) -> None` — 워치리스트+보유종목 심볼을 모아
    현재가를 조회하고 각 심의 `run()`을 호출.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_us_trade_loop.py
import datetime as dt
from zoneinfo import ZoneInfo
from unittest import mock

from scripts.us_trade_loop import is_us_market_open, run_cycle


def test_market_open_during_session_edt():
    # 2026-07-15(수) 14:00 UTC = 10:00 EDT — 개장 중
    now = dt.datetime(2026, 7, 15, 14, 0, tzinfo=dt.timezone.utc)
    assert is_us_market_open(now) is True


def test_market_closed_before_open_est():
    # 2026-01-15(목) 14:00 UTC = 09:00 EST — 개장 전(09:30 ET 시작)
    now = dt.datetime(2026, 1, 15, 14, 0, tzinfo=dt.timezone.utc)
    assert is_us_market_open(now) is False


def test_market_closed_on_weekend():
    now = dt.datetime(2026, 7, 18, 15, 0, tzinfo=dt.timezone.utc)  # 토요일
    assert is_us_market_open(now) is False


def test_market_closed_after_close():
    # 21:30 UTC = 17:30 EDT — 마감(16:00 ET) 후
    now = dt.datetime(2026, 7, 15, 21, 30, tzinfo=dt.timezone.utc)
    assert is_us_market_open(now) is False


class _FakeSim:
    def __init__(self):
        self.name = 'FakeUs'
        self.state = {'portfolio': {'TSLA': {'avg_price': 200.0}}}
        self.ran_with = None

    def get_universe(self):
        return [{'code': 'AAPL', 'pivot_price': 200.0, 'ma50': 190.0}]

    def run(self, candidates, current_prices):
        self.ran_with = (candidates, current_prices)


def test_run_cycle_fetches_watchlist_and_portfolio_prices():
    sim = _FakeSim()
    quotes = {'AAPL': {'price': 205.0, 'volume': 1000}, 'TSLA': {'price': 190.0, 'volume': 500}}
    fetch_quote = mock.Mock(side_effect=lambda sym: quotes.get(sym))
    run_cycle([sim], fetch_quote)
    candidates, current_prices = sim.ran_with
    assert current_prices == {'AAPL': 205.0, 'TSLA': 190.0}
    assert candidates[0]['code'] == 'AAPL'
    assert candidates[0]['price'] == 205.0
    assert candidates[0]['amount'] == 205.0 * 1000


def test_run_cycle_skips_symbol_with_no_quote():
    sim = _FakeSim()
    fetch_quote = mock.Mock(return_value=None)
    run_cycle([sim], fetch_quote)
    candidates, current_prices = sim.ran_with
    assert current_prices == {}
    assert candidates == []
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_us_trade_loop.py -q`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 구현**

```python
# scripts/us_trade_loop.py
"""US Sim1(이후 US 심 전체) 장중 페이퍼 체결 루프.

국내(trading.yml)는 태스커가 2분마다 repository_dispatch로 깨우는데, 그건
GitHub Actions 네이티브 cron이 부하 시 밀리는 지연이 **실손실**로 이어지기
때문이다. US 심은 페이퍼(자본 이동 없음)라 그 제약이 없다 — 네이티브 cron +
zoneinfo 게이트로 충분하고, 사용자 폰(태스커)이 한국시간 밤새 깨어 있을 필요가
없다.

    PYTHONPATH=. python scripts/us_trade_loop.py
"""
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data.us_ohlcv import fetch_current_quote  # noqa: E402
from src.strategy.us_registry import get_active_us_simulators  # noqa: E402

_NY = ZoneInfo('America/New_York')


def is_us_market_open(now_utc: dt.datetime | None = None) -> bool:
    """평일 09:30~16:00 ET. zoneinfo가 서머타임을 자동 반영한다."""
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    local = now_utc.astimezone(_NY)
    if local.weekday() >= 5:  # 토(5)·일(6)
        return False
    open_t = local.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = local.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_t <= local < close_t


def run_cycle(simulators, fetch_quote) -> None:
    """감시목록 + 보유종목 심볼만 조회해 각 심을 한 바퀴 돌린다."""
    for sim in simulators:
        candidates_raw = sim.get_universe() or []
        symbols = {c['code'] for c in candidates_raw if c.get('code')}
        symbols |= set(sim.state.get('portfolio', {}).keys())

        quotes = {}
        for code in symbols:
            q = fetch_quote(code)
            if q is not None:
                quotes[code] = q

        current_prices = {code: q['price'] for code, q in quotes.items()}
        candidates = []
        for c in candidates_raw:
            code = c.get('code')
            q = quotes.get(code)
            if q is None:
                continue
            entry = dict(c)
            entry['price'] = q['price']
            entry['amount'] = q['price'] * q['volume']
            candidates.append(entry)

        sim.run(candidates, current_prices)


def main():
    if not is_us_market_open():
        print('[US-Loop] 미국장 시간이 아님 — 종료')
        return
    simulators = get_active_us_simulators()
    run_cycle(simulators, fetch_current_quote)
    print(f'[US-Loop] {len(simulators)}개 심 실행 완료')


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_us_trade_loop.py -q`
Expected: PASS(6 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/us_trade_loop.py tests/test_us_trade_loop.py
git commit -m "feat(us): zoneinfo 기반 US 장중 페이퍼 체결 루프 추가"
```

---

## Task 10: GitHub Actions 워크플로 2개

**Files:**
- Create: `.github/workflows/us_eod_watchlist.yml`
- Create: `.github/workflows/us_trading.yml`

**Interfaces:**
- Consumes: Task 8의 `scripts/run_eod_sim_us.py`, Task 9의 `scripts/us_trade_loop.py`.
- 자동 테스트 없음(워크플로 문법은 `actionlint` 등 별도 도구가 없으면 실행 시점에만
  검증된다) — 대신 Step 3에서 `PYTHONPATH=. python scripts/*.py`가 로컬에서 정상
  종료하는지 수동 확인한다.

- [ ] **Step 1: EOD 워치리스트 워크플로 작성**

```yaml
# .github/workflows/us_eod_watchlist.yml
name: US EOD Watchlist (미국 심 감시목록)

# 하루 1회, 미국장 마감(16:00 ET) 이후 안전 마진을 둔 UTC 고정 시각에 돈다.
# 22:00 UTC는 EDT 마감(20:00 UTC)·EST 마감(21:00 UTC) 양쪽을 다 지난 시각이라
# 이 배치 자체는 서머타임 분기가 필요 없다.
on:
  schedule:
    - cron: '0 22 * * 2-6'  # 화~토 22:00 UTC(월~금 미국장 마감 다음)
  workflow_dispatch: {}

concurrency:
  group: us-eod-watchlist
  cancel-in-progress: false

jobs:
  watchlist:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    env:
      PYTHONPATH: ${{ github.workspace }}
      TZ: Asia/Seoul
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
          cache: 'pip'
          cache-dependency-path: 'scripts/requirements-trade.txt'

      - name: Install dependencies
        run: pip install -r scripts/requirements-trade.txt

      - name: Run EOD watchlist batch
        run: python scripts/run_eod_sim_us.py

      - name: Deploy watchlist (db-data)
        run: |
          git config --global user.email "github-actions[bot]@users.noreply.github.com"
          git config --global user.name "github-actions[bot]"
          git clone --depth 1 --branch db-data \
            https://x-access-token:${{ secrets.GITHUB_TOKEN }}@github.com/${{ github.repository }}.git db_data_repo || {
            echo "[Deploy] db-data 브랜치 clone 실패"; exit 1; }
          mkdir -p db_data_repo/data
          cp data/sim_us1_minervini_watchlist.json db_data_repo/data/ 2>/dev/null || true
          cp data/us_universe.json db_data_repo/data/ 2>/dev/null || true
          cd db_data_repo
          git add -A data/
          if git diff --cached --quiet; then echo "No changes"; exit 0; fi
          git commit -m "chore(us-eod): watchlist $(date +'%Y-%m-%d %H:%M UTC')"
          for i in 1 2 3; do
            if git push origin db-data; then exit 0; fi
            git fetch --unshallow origin db-data 2>/dev/null || git fetch origin db-data
            git pull --rebase origin db-data || { echo "rebase 실패"; exit 1; }
          done
          exit 1
```

- [ ] **Step 2: 장중 루프 워크플로 작성**

```yaml
# .github/workflows/us_trading.yml
name: US Trading (미국 심 페이퍼 매매)

# 페이퍼 전용(자본 이동 없음)이라 태스커 없이 네이티브 cron을 쓴다. UTC 13:00~21:30은
# EDT 세션(13:30~20:00 UTC)과 EST 세션(14:30~21:00 UTC) 양쪽을 다 덮는 넓은 창이고,
# 실제 개장 여부는 us_trade_loop.py 내부의 zoneinfo 게이트가 판정한다(서머타임 자동
# 반영) — 이 cron 표현식 자체는 서머타임을 몰라도 된다.
on:
  schedule:
    - cron: '*/5 13-21 * * 1-5'
  workflow_dispatch: {}

concurrency:
  group: us-trading
  cancel-in-progress: false

jobs:
  trade:
    runs-on: ubuntu-latest
    timeout-minutes: 4
    env:
      PYTHONPATH: ${{ github.workspace }}
      TZ: Asia/Seoul
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
          cache: 'pip'
          cache-dependency-path: 'scripts/requirements-trade.txt'

      - name: Install dependencies
        run: pip install -r scripts/requirements-trade.txt

      - name: Fetch remote state (db-data)
        run: |
          git fetch --depth 1 origin db-data:db-data 2>/dev/null || echo "[Info] db-data 없음"
          if git show-ref --verify refs/heads/db-data 2>/dev/null; then
            git checkout db-data -- data/ 2>/dev/null || true
          fi
          mkdir -p data

      - name: Run US trade loop
        run: python scripts/us_trade_loop.py

      - name: Deploy state (db-data)
        run: |
          git config --global user.email "github-actions[bot]@users.noreply.github.com"
          git config --global user.name "github-actions[bot]"
          git clone --depth 1 --branch db-data \
            https://x-access-token:${{ secrets.GITHUB_TOKEN }}@github.com/${{ github.repository }}.git db_data_repo || {
            echo "[Deploy] clone 실패"; exit 1; }
          mkdir -p db_data_repo/data
          cp data/sim_us1minervini_state.json db_data_repo/data/ 2>/dev/null || true
          cp data/trade_history_sim_us1minervini.csv db_data_repo/data/ 2>/dev/null || true
          cd db_data_repo
          git add -A data/
          if git diff --cached --quiet; then echo "No changes"; exit 0; fi
          git commit -m "chore(us-trade): sim state $(date +'%Y-%m-%d %H:%M UTC')"
          for i in 1 2 3; do
            if git push origin db-data; then exit 0; fi
            git fetch --unshallow origin db-data 2>/dev/null || git fetch origin db-data
            git pull --rebase origin db-data || { echo "rebase 실패"; exit 1; }
          done
          exit 1
```

- [ ] **Step 3: 로컬 수동 검증**

Run: `PYTHONPATH=. python scripts/run_eod_sim_us.py` (네트워크가 되는 환경에서;
안 되면 예외가 나는 것까지가 정상 — 0으로 조용히 넘어가지 않아야 한다)
Run: `PYTHONPATH=. python scripts/us_trade_loop.py` (개장 시간이 아니면
"미국장 시간이 아님 — 종료"가 찍히는지 확인)

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/us_eod_watchlist.yml .github/workflows/us_trading.yml
git commit -m "ci(us): EOD 워치리스트 배치·장중 페이퍼 루프 워크플로 추가"
```

---

## Task 11: 통화 포맷 유틸리티

**Files:**
- Create: `src/lib/currency-format.ts`
- Test: `src/lib/currency-format.test.ts`

**Interfaces:**
- Produces: `formatMoney(value: number, currency: 'KRW' | 'USD') -> string`
  (`KRW`: 반올림 정수 + `'원'`, `USD`: `'$'` + 소수점 2자리 콤마 포맷)

- [ ] **Step 1: 실패 테스트 작성**

```typescript
// src/lib/currency-format.test.ts
import { test } from 'node:test';
import assert from 'node:assert';
import { formatMoney } from './currency-format.ts';

test('KRW는 반올림 정수 + 원', () => {
  assert.equal(formatMoney(1234567.8, 'KRW'), '1,234,568원');
});

test('USD는 소수점 2자리 + $ 접두', () => {
  assert.equal(formatMoney(45.6, 'USD'), '$45.60');
  assert.equal(formatMoney(12345.678, 'USD'), '$12,345.68');
});

test('음수도 부호를 보존한다', () => {
  assert.equal(formatMoney(-45.6, 'USD'), '-$45.60');
  assert.equal(formatMoney(-1000, 'KRW'), '-1,000원');
});
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `node --test "src/lib/currency-format.test.ts"`
Expected: FAIL(모듈 없음)

- [ ] **Step 3: 구현**

```typescript
// src/lib/currency-format.ts
/** 심 카드·포트폴리오 표에서 쓰는 통화 표시. KRW는 국내 심(정수 원),
 * USD는 US 심(소수점 2자리) — 기본값 KRW로 기존 화면과 100% 동일하게 유지한다. */
export function formatMoney(value: number, currency: 'KRW' | 'USD' = 'KRW'): string {
  if (currency === 'USD') {
    const sign = value < 0 ? '-' : '';
    const abs = Math.abs(value);
    return `${sign}$${abs.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  return `${Math.round(value).toLocaleString()}원`;
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `node --test "src/lib/currency-format.test.ts"`
Expected: PASS(3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/lib/currency-format.ts src/lib/currency-format.test.ts
git commit -m "feat(us): KRW/USD 공용 통화 포맷 유틸리티 추가"
```

---

## Task 12: `SimCard`/`PortfolioTable`에 통화 prop 추가

**Files:**
- Modify: `src/app/trade/SimCard.tsx:18-30, 44-45, 55-56, 61`
- Modify: `src/app/trade/PortfolioTable.tsx`(가격 표시 5곳)

**Interfaces:**
- Consumes: `formatMoney`(Task 11)
- Produces: `SimCard`/`PortfolioTable`에 `currency?: 'KRW' | 'USD'`(기본 `'KRW'`) prop 추가.
  기존 호출부(`TradeClient.tsx`)는 prop을 안 넘기므로 동작 100% 동일.

- [ ] **Step 1: `PortfolioTable.tsx`에 currency prop 추가(전체 교체)**

```tsx
// src/app/trade/PortfolioTable.tsx
'use client';

import { Table, Text, Badge, Checkbox, ScrollArea, Box } from '@mantine/core';
import { derivePosition, pnlColor } from '@/lib/trade-display';
import { formatMoney } from '@/lib/currency-format';

/**
 * 보유 종목 표. 실계좌(isReal)일 때만 일괄매도용 체크박스 열이 붙는다.
 *
 * TradeClient.tsx 안의 renderPortfolioTable을 그대로 옮겼다 — 그 함수는 인자 셋을
 * 받으면서도 선택 상태·종목 선택·알림을 클로저로 끌고 있었다. 여기서는 전부 prop이라
 * 이 표가 무엇에 의존하는지가 시그니처에 다 적혀 있다.
 */
export default function PortfolioTable({
    holdings, isReal = false, maxHeight = 560, selectedCodes = [], onToggleCode, onPickCode,
    currency = 'KRW',
}: {
    holdings: any[];
    isReal?: boolean;
    maxHeight?: string | number;
    /** 일괄매도 선택 상태. isReal일 때만 쓰인다 — 심 카드는 넘기지 않는다. */
    selectedCodes?: string[];
    onToggleCode?: (code: string, checked: boolean) => void;
    onPickCode: (code: string, name: string) => void;
    currency?: 'KRW' | 'USD';
}) {
    if (!holdings || holdings.length === 0) {
        return (
            <Box style={{ height: 120, textAlign: 'center', border: '1px dashed #ced4da', borderRadius: '8px', width: '100%', minWidth: isReal ? 650 : 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Text c="dimmed">보유 종목이 없습니다.</Text>
            </Box>
        );
    }
    return (
        <ScrollArea.Autosize mah={maxHeight} offsetScrollbars>
            <Table striped highlightOnHover verticalSpacing="xs" style={{ minWidth: isReal ? 650 : 600 }}>
                <Table.Thead>
                    <Table.Tr>
                        {isReal && <Table.Th style={{ width: 40, position: 'sticky', left: 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 2 }}></Table.Th>}
                        <Table.Th style={{ width: 120, position: 'sticky', left: isReal ? 40 : 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 1, borderRight: '1px solid #eee' }}>종목명</Table.Th>
                        <Table.Th style={{ textAlign: 'right' }}>수량</Table.Th>
                        <Table.Th style={{ textAlign: 'right' }}>평단가</Table.Th>
                        <Table.Th style={{ textAlign: 'right' }}>현재가</Table.Th>
                        <Table.Th style={{ textAlign: 'right' }}>체결금액</Table.Th>
                        <Table.Th style={{ textAlign: 'center' }}>수익률(%)</Table.Th>
                        <Table.Th style={{ textAlign: 'right' }}>손익({currency === 'USD' ? '$' : '원'})</Table.Th>
                    </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                    {holdings.map((h) => {
                        const { qty, avgPrice, currentPrice, amount, plRate, plAmount, priceKnown } = derivePosition(h);
                        const isSelected = selectedCodes.includes(h.code);

                        return (
                            <Table.Tr key={h.code} style={{ cursor: isReal ? 'pointer' : 'default' }}>
                                {isReal && (
                                    <Table.Td onClick={(e) => e.stopPropagation()} style={{ position: 'sticky', left: 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 2 }}>
                                        <Checkbox
                                            checked={isSelected}
                                            onChange={(event) => onToggleCode?.(h.code, event.currentTarget.checked)}
                                        />
                                    </Table.Td>
                                )}
                                <Table.Td
                                    onClick={() => onPickCode(h.code, h.name)}
                                    style={{ cursor: 'pointer', position: 'sticky', left: isReal ? 40 : 0, backgroundColor: 'var(--mantine-color-body)', zIndex: 1, borderRight: '1px solid #eee' }}
                                >
                                    <Text size="sm" fw={700} truncate maw={100} c="blue" style={{ textDecoration: 'underline', textUnderlineOffset: '2px' }}>{h.name}</Text>
                                    <Text size="xs" c="dimmed">{h.code}</Text>
                                </Table.Td>
                                <Table.Td style={{ textAlign: 'right' }}>
                                    <Text size="sm">{qty.toLocaleString()}주</Text>
                                </Table.Td>
                                <Table.Td style={{ textAlign: 'right' }}>
                                    <Text size="sm">{formatMoney(avgPrice, currency)}</Text>
                                </Table.Td>
                                <Table.Td style={{ textAlign: 'right' }}>
                                    {priceKnown
                                        ? <Text size="sm" fw={500} c="teal">{formatMoney(currentPrice, currency)}</Text>
                                        : <Text size="sm" c="dimmed">시세 미확인</Text>}
                                </Table.Td>
                                <Table.Td style={{ textAlign: 'right' }}>
                                    <Text size="sm" fw={700}>{formatMoney(amount, currency)}</Text>
                                </Table.Td>
                                <Table.Td style={{ textAlign: 'center' }}>
                                    {/* 시세를 모르면 등락률도 모른다. 0%로 그리면 '안 움직였다'는 거짓이 된다. */}
                                    {priceKnown ? (
                                        <Badge color={pnlColor(plRate)} variant="filled" size="sm" style={{ width: 65 }}>
                                            {plRate >= 0 ? '+' : ''}{plRate.toFixed(2)}%
                                        </Badge>
                                    ) : (
                                        <Text size="xs" c="dimmed">측정 불가</Text>
                                    )}
                                </Table.Td>
                                <Table.Td style={{ textAlign: 'right' }}>
                                    {priceKnown
                                        ? <Text size="sm" fw={700} c={pnlColor(plAmount)}>{plAmount >= 0 ? '+' : ''}{formatMoney(plAmount, currency)}</Text>
                                        : <Text size="xs" c="dimmed">측정 불가</Text>}
                                </Table.Td>
                            </Table.Tr>
                        );
                    })}
                </Table.Tbody>
            </Table>
        </ScrollArea.Autosize>
    );
}
```

기존 `signed(plAmount)` 호출을 걷어냈다 — `formatMoney`가 이미 음수 부호(`-$`)를
만들고, 양수엔 위 삼항식이 `+`를 앞에 붙인다(이중 부호 방지). `signed`는
`@/lib/trade-display`의 다른 소비자(실계좌 요약 등)가 여전히 쓰므로 그 함수
자체는 건드리지 않는다 — import에서 `signed`만 뺐다.

- [ ] **Step 2: `SimCard.tsx`에 currency prop 추가**

```tsx
// src/app/trade/SimCard.tsx (변경분만)
import { formatMoney } from '@/lib/currency-format';
// ...
export default function SimCard({
    uiKey, label, color, type, stats, portfolio, history, onPickCode, onShowReason,
    currency = 'KRW',
}: {
    uiKey: string;
    label: string;
    color: string;
    type: string;
    stats: any;
    portfolio: Record<string, any>;
    history: any[];
    onPickCode: (code: string, name: string) => void;
    onShowReason: (title: string, content: string) => void;
    currency?: 'KRW' | 'USD';
}) {
    // ... 기존 로직 동일 ...
    return (
        <Stack gap="sm">
            <Paper p="md" withBorder radius="md" style={{ borderTop: `4px solid var(--mantine-color-${color}-filled)` }}>
                <Group justify="space-between" mb="xs">
                    <Text fw={800} size="lg" c={color}>{label}</Text>
                    <Badge color={color}>{uiKey.toUpperCase()}</Badge>
                </Group>
                <SimpleGrid cols={{ base: 3, sm: 6 }} mb="md">
                    <Stack gap={2}>
                        <Text size="xs" c="dimmed">예수금</Text>
                        <Text fw={700} size="sm">{formatMoney(stats.cash || 0, currency)}</Text>
                    </Stack>
                    <Stack gap={2}>
                        <Text size="xs" c="dimmed">수익률</Text>
                        <Text size="sm" fw={800} c={(stats.profit_rate || 0) >= 0 ? 'red' : 'blue'}>
                            {(stats.profit_rate || 0).toFixed(2)}%
                        </Text>
                    </Stack>
                    <Stack gap={2}>
                        <Text size="xs" c="dimmed">누적 수익</Text>
                        <Text size="sm" fw={800} c={netPL >= 0 ? 'red' : 'blue'}>
                            {netPL >= 0 ? '+' : ''}{formatMoney(netPL, currency)}
                        </Text>
                    </Stack>
                    <Stack gap={2}>
                        <Text size="xs" c="dimmed">누적 수수료</Text>
                        <Text size="sm" fw={700} c="gray.6">{formatMoney(stats.total_fees || 0, currency)}</Text>
                    </Stack>
                    <Stack gap={2}>
                        <Text size="xs" c="dimmed">보유 종목</Text>
                        <Text size="sm" fw={800} c={color}>{holdings.length}개</Text>
                    </Stack>
                    <Stack gap={2}>
                        <Text size="xs" c="dimmed">금일 거래</Text>
                        <Text size="sm" fw={800} c={todayTickerCount > 0 ? 'dark' : 'dimmed'}>{todayTickerCount}종목</Text>
                    </Stack>
                </SimpleGrid>
                <Divider mb="xs" label="포트폴리오 (NAV)" labelPosition="center" />
                <PortfolioTable holdings={holdings} maxHeight={360} onPickCode={onPickCode} currency={currency} />
            </Paper>
            <Paper p="md" withBorder radius="md" bg="gray.0">
                <Text size="xs" fw={700} mb="xs"><IconHistory size={12} style={{ marginRight: 5 }}/>{label} 기록</Text>
                <TradeHistoryTable history={history} targetType={type} maxHeight={305} onShowReason={onShowReason} />
            </Paper>
        </Stack>
    );
}
```

- [ ] **Step 3: 타입 검사로 기존 호출부(`TradeClient.tsx`) 무변경 확인**

Run: `npx tsc --noEmit`
Expected: 에러 없음(`currency`가 선택 prop이라 기존 `<SimCard ... />` 호출이 그대로 컴파일된다)

- [ ] **Step 4: Commit**

```bash
git add src/app/trade/SimCard.tsx src/app/trade/PortfolioTable.tsx
git commit -m "feat(us): SimCard·PortfolioTable에 currency prop 추가(기본 KRW, 기존 동작 보존)"
```

---

## Task 13: USD 리셋 API

**Files:**
- Create: `src/lib/us-sim-reset-targets.ts`
- Create: `src/app/api/simulation/reset-us/route.ts`
- Test: `src/lib/us-sim-reset-targets.test.ts`

**Interfaces:**
- Consumes: `US_SIM_REGISTRY`(Task 7), `commitFilesAtomically`(기존 `@/lib/github-tree-commit`),
  `buildResetState`(기존 `@/lib/sim-registry.generated`, 국내와 shape 재사용).
- Produces: `US_RESET_TARGETS: ResetTarget[]`, `validateUsCash(cash: unknown) -> {ok,...}`
  (`$1,000~$500,000` 정수).

- [ ] **Step 1: 실패 테스트 작성**

```typescript
// src/lib/us-sim-reset-targets.test.ts
import { test } from 'node:test';
import assert from 'node:assert';
import { US_RESET_TARGETS, validateUsCash } from './us-sim-reset-targets.ts';

test('US_RESET_TARGETS는 us_sim1 하나', () => {
  assert.equal(US_RESET_TARGETS.length, 1);
  assert.equal(US_RESET_TARGETS[0].id, 'us_sim1');
  assert.equal(US_RESET_TARGETS[0].stateFile, 'sim_us1minervini_state.json');
});

test('validateUsCash 경계값', () => {
  assert.equal(validateUsCash(20000).ok, true);
  assert.equal(validateUsCash(1000).ok, true);
  assert.equal(validateUsCash(500000).ok, true);
  assert.equal(validateUsCash(999).ok, false);
  assert.equal(validateUsCash(500001).ok, false);
  assert.equal(validateUsCash(20000.5).ok, false);
  assert.equal(validateUsCash('20000').ok, false);
});
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `node --test "src/lib/us-sim-reset-targets.test.ts"`
Expected: FAIL(모듈 없음)

- [ ] **Step 3: 구현**

```typescript
// src/lib/us-sim-reset-targets.ts
import { US_SIM_REGISTRY } from './us-sim-registry.generated.ts';
import { buildResetState, TRADE_CSV_HEADER as RESET_CSV_HEADER } from './sim-registry.generated.ts';

export interface ResetTarget { id: string; stateFile: string; csvFile: string; }

export const US_RESET_TARGETS: ResetTarget[] = US_SIM_REGISTRY.map((s) => ({
  id: s.uiKey, stateFile: s.stateFile, csvFile: s.csvFile,
}));

export { buildResetState, RESET_CSV_HEADER };

export function validateUsCash(cash: unknown): { ok: true; value: number } | { ok: false; error: string } {
  if (typeof cash !== 'number' || !Number.isInteger(cash)) {
    return { ok: false, error: '예수금은 정수여야 합니다' };
  }
  if (cash < 1_000 || cash > 500_000) {
    return { ok: false, error: '예수금은 $1,000 ~ $500,000 사이여야 합니다' };
  }
  return { ok: true, value: cash };
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `node --test "src/lib/us-sim-reset-targets.test.ts"`
Expected: PASS(2 passed)

- [ ] **Step 5: 리셋 API 라우트 작성**

```typescript
// src/app/api/simulation/reset-us/route.ts
import { NextResponse } from 'next/server';
import { getToken } from 'next-auth/jwt';
import { US_RESET_TARGETS, RESET_CSV_HEADER, buildResetState, validateUsCash } from '@/lib/us-sim-reset-targets';
import { commitFilesAtomically } from '@/lib/github-tree-commit';

export const dynamic = 'force-dynamic';

const OWNER = 'hoonnamkoong';
const REPO = 'stockbot';
const BRANCH = 'db-data';
const GITHUB_PAT = process.env.GITHUB_PAT || process.env.GITHUB_TOKEN;

export async function POST(request: Request) {
  const token = await getToken({ req: request as any, secret: process.env.NEXTAUTH_SECRET });
  if (!token) return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  if (!GITHUB_PAT) return NextResponse.json({ success: false, error: 'Server auth not configured' }, { status: 500 });

  let body: any;
  try { body = await request.json(); } catch { return NextResponse.json({ success: false, error: '잘못된 요청' }, { status: 400 }); }

  const v = validateUsCash(body?.cash);
  if (!v.ok) return NextResponse.json({ success: false, error: v.error }, { status: 400 });

  const stateJson = JSON.stringify(buildResetState(v.value), null, 2);
  const files = US_RESET_TARGETS.flatMap(t => ([
    { path: `data/${t.stateFile}`, content: stateJson },
    { path: `data/${t.csvFile}`, content: RESET_CSV_HEADER },
  ]));

  try {
    await commitFilesAtomically({
      owner: OWNER, repo: REPO, branch: BRANCH, token: GITHUB_PAT,
      message: `chore(us-sim): reset ${US_RESET_TARGETS.length} US simulators to $${v.value} (dashboard)`,
      files,
    });
  } catch (e: any) {
    return NextResponse.json({ success: false, error: `리셋 실패: ${e?.message ?? e}` }, { status: 500 });
  }

  return NextResponse.json({ success: true, cash: v.value, sims: US_RESET_TARGETS.map(t => t.id) });
}
```

- [ ] **Step 6: 타입 검사**

Run: `npx tsc --noEmit`
Expected: 에러 없음

- [ ] **Step 7: Commit**

```bash
git add src/lib/us-sim-reset-targets.ts src/lib/us-sim-reset-targets.test.ts src/app/api/simulation/reset-us/route.ts
git commit -m "feat(us): USD 전용 리셋 대상·API 추가"
```

---

## Task 14: US 통계·기록 API

**Files:**
- Create: `src/app/api/simulation/stats-us/route.ts`
- Create: `src/app/api/trade/history-us/route.ts`

**Interfaces:**
- Consumes: `US_SIM_REGISTRY`(Task 7), 기존 `@/lib/db-data`(`createBucketCache`, `dbDataUrl`),
  기존 `@/lib/trade-history-csv`(`parseSimHistoryCsv`, 통화 무관 — 수정 없이 재사용).
- Produces:
  - `stats-us` `GET` — `{ [uiKey]: { raw, normalized, portfolio }, last_updated }`(리베로 블록 없음).
  - `history-us` `GET` — `{ success, count, data }`(`data[].type`이 매니페스트 `id`와 일치,
    `TradeUSClient`의 `SimCard`가 넘기는 `type` prop과 맞아야 기록 표가 채워진다).

- [ ] **Step 1: 통계 API 구현**

`src/app/api/simulation/stats/route.ts`(Task 이전에 읽은 파일)와 동일 구조에서
`SIM_REGISTRY`/`ANALYZERS` import와 리베로 블록만 뺀다.

```typescript
// src/app/api/simulation/stats-us/route.ts
import { NextResponse } from 'next/server';
import { US_SIM_REGISTRY } from '@/lib/us-sim-registry.generated';
import { createBucketCache, dbDataUrl } from '@/lib/db-data';

export const dynamic = 'force-dynamic';

const loadStats = createBucketCache(async () => {
    const types = US_SIM_REGISTRY.map((s) => ({ id: s.uiKey, file: s.stateFile }));
    const results: any = {};

    await Promise.all(types.map(async (type) => {
        try {
            const res = await fetch(dbDataUrl(type.file), { cache: 'no-store' });
            if (!res.ok) throw new Error(`Fetch failed for ${type.file}`);
            const state = await res.json();

            const currentPrices = state.raw_stats?.current_prices || {};
            let portfolioValue = 0;
            if (state.portfolio) {
                Object.entries(state.portfolio).forEach(([code, item]: [string, any]) => {
                    const price = currentPrices[code] || item.current_price || item.avg_price || 0;
                    const qty = item.quantity || item.qty || 0;
                    portfolioValue += price * qty;
                });
            }

            const liveCash = state.cash || 0;
            const totalAsset = liveCash + portfolioValue;
            const initialCash = state.initial_cash || 20000;
            const profit = totalAsset - initialCash;
            const returnRate = initialCash > 0 ? (profit / initialCash) * 100 : 0;

            results[type.id] = {
                raw: {
                    ...(state.raw_stats || {}),
                    cash: liveCash,
                    portfolio_value: portfolioValue,
                    total_asset: totalAsset,
                    profit,
                    profit_rate: returnRate,
                },
                normalized: state.normalized_stats || {},
                portfolio: state.portfolio || {}
            };
        } catch (err) {
            console.error(`[StatsAPI-US] Error processing ${type.id}:`, err);
            results[type.id] = { raw: {}, portfolio: {} };
        }
    }));

    results["last_updated"] = new Date().toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' });
    return results;
});

export async function GET() {
    try {
        return NextResponse.json(await loadStats());
    } catch (error: any) {
        console.error('[Simulation API US] Error fetching stats:', error);
        return NextResponse.json(
            { error: 'Failed to fetch simulation stats', details: error.message },
            { status: 500 }
        );
    }
}
```

- [ ] **Step 2: 기록 API 구현**

`src/app/api/trade/history/route.ts`(국내)의 심 CSV 파싱 부분만 옮긴다 — 실거래
(`fetchRealHistory`) 블록은 없다(US 심은 페이퍼 전용).

```typescript
// src/app/api/trade/history-us/route.ts
import { NextResponse } from 'next/server';
import { US_SIM_REGISTRY } from '@/lib/us-sim-registry.generated';
import { createBucketCache, dbDataUrl } from '@/lib/db-data';
import { parseSimHistoryCsv } from '@/lib/trade-history-csv';

export const dynamic = 'force-dynamic';

async function fetchSimHistory(fileInfo: { type: string; name: string }) {
    try {
        const res = await fetch(dbDataUrl(fileInfo.name), { cache: 'no-store' });
        if (!res.ok) return [];
        return parseSimHistoryCsv(await res.text(), fileInfo.type);
    } catch (err) {
        console.error(`[HistoryAPI-US] Error fetching ${fileInfo.name}:`, err);
        return [];
    }
}

const loadUsSimHistories = createBucketCache(async () => {
    const simFiles = US_SIM_REGISTRY.map((s) => ({ type: s.id, name: s.csvFile }));
    const histories = await Promise.all(simFiles.map(fetchSimHistory));
    return histories.flat();
});

export async function GET() {
    try {
        const data = await loadUsSimHistories();
        data.sort((a: any, b: any) => {
            const timeA = new Date(a.time).getTime();
            const timeB = new Date(b.time).getTime();
            return isNaN(timeB) || isNaN(timeA) ? 0 : timeB - timeA;
        });
        return NextResponse.json({ success: true, count: data.length, data });
    } catch (error: any) {
        return NextResponse.json(
            { success: false, error: 'Failed to fetch US trade history', details: error.message },
            { status: 500 }
        );
    }
}
```

- [ ] **Step 3: 타입 검사**

Run: `npx tsc --noEmit`
Expected: 에러 없음

- [ ] **Step 4: Commit**

```bash
git add src/app/api/simulation/stats-us/route.ts src/app/api/trade/history-us/route.ts
git commit -m "feat(us): US 심 통계·기록 API 추가"
```

---

## Task 15: `/trade/us` 페이지

**Files:**
- Create: `src/app/trade/us/page.tsx`
- Create: `src/app/trade/us/TradeUSClient.tsx`

**Interfaces:**
- Consumes: `SimCard`(Task 12, `currency="USD"`), `/api/simulation/stats-us`,
  `/api/trade/history-us`(둘 다 Task 14), `/api/simulation/reset-us`(Task 13),
  `US_SIM_REGISTRY`(Task 7).
- `middleware.ts`의 `matcher: ["/trade/:path*", ...]`가 이미 이 경로를 보호한다 —
  수정 불필요.

- [ ] **Step 1: page.tsx**

```tsx
// src/app/trade/us/page.tsx
import TradeUSClient from './TradeUSClient';

export const dynamic = 'force-dynamic';

export default function TradeUSPage() {
    return <TradeUSClient />;
}
```

- [ ] **Step 2: TradeUSClient.tsx**

국내 `TradeClient.tsx`(리셋 입력·모달·심 카드 목록 렌더)의 최소 축소판이다.
실계좌 요약·`useProgramTrading` 등 실거래 전용 UI는 없다 — 페이퍼 전용 페이지다.

```tsx
// src/app/trade/us/TradeUSClient.tsx
'use client';

import { useEffect, useState } from 'react';
import { Container, Title, Text, Group, Button, NumberInput, Modal, SimpleGrid, Anchor, Alert } from '@mantine/core';
import Link from 'next/link';
import SimCard from '../SimCard';
import { US_SIM_REGISTRY } from '@/lib/us-sim-registry.generated';

export default function TradeUSClient() {
    const [stats, setStats] = useState<any>({});
    const [history, setHistory] = useState<any[]>([]);
    const [resetCash, setResetCash] = useState<number | ''>(20000);
    const [resetConfirmOpen, setResetConfirmOpen] = useState(false);
    const [resetBusy, setResetBusy] = useState(false);

    async function load() {
        const [statsRes, historyRes] = await Promise.all([
            fetch('/api/simulation/stats-us', { cache: 'no-store' }),
            fetch('/api/trade/history-us', { cache: 'no-store' }),
        ]);
        setStats(await statsRes.json());
        const historyBody = await historyRes.json();
        setHistory(historyBody.data ?? []);
    }

    useEffect(() => {
        load();
        const t = setInterval(load, 30_000);
        return () => clearInterval(t);
    }, []);

    async function handleReset() {
        if (typeof resetCash !== 'number' || !Number.isInteger(resetCash) || resetCash < 1000 || resetCash > 500000) {
            return;
        }
        setResetBusy(true);
        try {
            await fetch('/api/simulation/reset-us', {
                method: 'POST',
                body: JSON.stringify({ cash: resetCash }),
            });
            await load();
        } finally {
            setResetBusy(false);
            setResetConfirmOpen(false);
        }
    }

    return (
        <Container size="xl" py="md">
            <Group justify="space-between" mb="md">
                <Title order={2}>미국 트레이딩 (페이퍼)</Title>
                <Anchor component={Link} href="/trade">국내 트레이딩으로</Anchor>
            </Group>
            <Alert color="blue" mb="md">
                페이퍼(관찰) 전용입니다 — 실주문 연동 없음, 자본 이동 없음.
            </Alert>
            <Group mb="lg">
                <NumberInput
                    placeholder="예수금(USD)"
                    value={resetCash}
                    onChange={(v) => setResetCash(typeof v === 'number' ? v : '')}
                    disabled={resetBusy}
                    min={1000}
                    max={500000}
                />
                <Button color="red" size="xs" onClick={() => setResetConfirmOpen(true)} disabled={resetBusy} loading={resetBusy}>
                    전체 리셋
                </Button>
            </Group>
            <SimpleGrid cols={{ base: 1, lg: 2 }}>
                {US_SIM_REGISTRY.map((s) => (
                    <SimCard
                        key={s.id}
                        uiKey={s.uiKey}
                        label={s.label}
                        color={s.color}
                        type={s.id}
                        stats={stats[s.uiKey]?.raw ?? {}}
                        portfolio={stats[s.uiKey]?.portfolio ?? {}}
                        history={history}
                        onPickCode={() => {}}
                        onShowReason={() => {}}
                        currency="USD"
                    />
                ))}
            </SimpleGrid>
            <Modal opened={resetConfirmOpen} onClose={() => setResetConfirmOpen(false)} title="정말 초기화할까요?" centered>
                <Text size="sm" mb="md">
                    US 심 전체를 <b>{typeof resetCash === 'number' ? `$${resetCash.toLocaleString()}` : '-'}</b>로 초기화합니다.
                </Text>
                <Group justify="flex-end">
                    <Button variant="default" onClick={() => setResetConfirmOpen(false)} disabled={resetBusy}>취소</Button>
                    <Button color="red" onClick={handleReset} disabled={resetBusy} loading={resetBusy}>초기화</Button>
                </Group>
            </Modal>
        </Container>
    );
}
```

- [ ] **Step 3: 타입 검사**

Run: `npx tsc --noEmit`
Expected: 에러 없음

- [ ] **Step 4: 개발 서버로 육안 확인**

Run: `npm run dev` (백그라운드) → 브라우저로 `/trade/us` 접속 (로그인 필요 시
기존 계정으로 로그인) → 심 카드가 `$` 단위로 렌더되는지, 리셋 버튼이 동작하는지
확인. 확인 후 `Ctrl+C`로 dev 서버 종료.

- [ ] **Step 5: Commit**

```bash
git add src/app/trade/us/page.tsx src/app/trade/us/TradeUSClient.tsx
git commit -m "feat(us): /trade/us 페이지 추가"
```

---

## Task 16: 국내 `/trade` 페이지에 미국 링크 추가

**Files:**
- Modify: `src/app/trade/TradeClient.tsx:3, 10, 744`

**Interfaces:**
- Consumes: 없음(순수 UI 추가)
- 국내 페이지의 기존 상태·로직·API 호출은 전혀 건드리지 않는다 — 헤더 타이틀 문구와
  `/trade/us` 링크 한 줄만 추가한다.

- [ ] **Step 1: `next/link` import 추가**

`src/app/trade/TradeClient.tsx:3`(기존 React 훅 import 줄) 바로 아래에 추가:

```tsx
import dynamic from 'next/dynamic';
import Link from 'next/link';
```

- [ ] **Step 2: `Anchor` 컴포넌트 import 추가**

`src/app/trade/TradeClient.tsx:7-11`의 Mantine import 목록에 `Anchor`를 추가:

```tsx
import {
    Container, Title, Text, Paper, Group, Stack, SimpleGrid,
    Badge, Button, Tabs, TextInput, NumberInput,
    Select, Switch, Notification, LoadingOverlay, Modal, PinInput, Affix, Transition, Box, Divider, Alert,
    Anchor
} from '@mantine/core';
```

- [ ] **Step 3: 헤더 타이틀을 "국내 트레이딩"으로 바꾸고 미국 링크 추가**

`src/app/trade/TradeClient.tsx:743-750`(현재 `<Title order={2}>Stock Dashboard</Title>`가
있는 헤더 `<Group>`)을 교체:

```tsx
// 기존(변경 전):
//             <Group justify="space-between" mb="lg">
//                 <Title order={2}>Stock Dashboard</Title>
//                 <Group gap="xs">
//                     <Badge color="pink" variant="filled">V8.7.2-UI</Badge>
//                     <Button component="a" href="/research" size="sm" variant="light">Research</Button>
//                     <Button color="gray" variant="subtle" size="sm" onClick={() => signOut({ callbackUrl: '/login' })}>Out</Button>
//                 </Group>
//             </Group>

            <Group justify="space-between" mb="lg">
                <Group gap="sm">
                    <Title order={2}>국내 트레이딩</Title>
                    <Anchor component={Link} href="/trade/us" size="sm">미국 →</Anchor>
                </Group>
                <Group gap="xs">
                    <Badge color="pink" variant="filled">V8.7.2-UI</Badge>
                    <Button component="a" href="/research" size="sm" variant="light">Research</Button>
                    <Button color="gray" variant="subtle" size="sm" onClick={() => signOut({ callbackUrl: '/login' })}>Out</Button>
                </Group>
            </Group>
```

- [ ] **Step 4: 타입 검사 + 개발 서버 육안 확인**

Run: `npx tsc --noEmit`
Run: `npm run dev` → `/trade` 접속 → 제목이 "국내 트레이딩"으로 보이고 "미국 →"
링크가 `/trade/us`로 이동하는지 확인. 기존 심 카드·리셋·기록 표가 그대로
동작하는지도 함께 확인(회귀 없음 확인).

- [ ] **Step 5: Commit**

```bash
git add src/app/trade/TradeClient.tsx
git commit -m "feat(us): 국내 트레이딩 페이지에 미국 트레이딩 링크 추가"
```

---

## Task 17: 전체 검증

**Files:** 없음(검증만)

- [ ] **Step 1: 전체 파이썬 테스트**

Run: `python -m pytest tests/ -q`
Expected: 전부 PASS(기존 테스트 포함, 회귀 없음)

- [ ] **Step 2: 전체 TS 테스트 + 타입 검사**

Run: `node --test "src/**/*.test.ts"`
Run: `npx tsc --noEmit`
Expected: 전부 PASS, 타입 에러 없음

- [ ] **Step 3: 레지스트리 생성 결과가 최신인지 재확인**

Run: `PYTHONPATH=. python scripts/gen_us_sim_registry.py`
Expected: `git diff --stat src/lib/us-sim-registry.generated.ts`가 빈 출력(이미 최신)

- [ ] **Step 4: 국내 회귀 확인**

Run: `python -m pytest tests/test_sim_registry_consistency.py tests/test_run_simulators_lite_mode.py -q`
Expected: PASS — US 심 추가가 국내 `_run_simulators`/매니페스트 일관성에
영향을 주지 않았음을 확인.
