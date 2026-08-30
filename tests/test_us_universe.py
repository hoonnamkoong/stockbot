import json
import os
import tempfile
from unittest import mock

from src.data import us_universe
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


def test_fetch_us_universe_raises_on_empty_rows():
    """HTTP 200이어도 rows가 null/비어있으면 (재시도 뒤) 예외를 올린다."""
    with mock.patch('src.data.us_universe.requests.get') as m,          mock.patch('src.data.us_universe.time.sleep'):
        m.return_value.status_code = 200
        m.return_value.json.return_value = {'data': {'table': {'rows': None}, 'rows': None}}
        m.return_value.raise_for_status = lambda: None
        try:
            fetch_us_universe(limit=10)
            assert False, '예외가 나야 한다'
        except RuntimeError as e:
            assert 'rows' in str(e)


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


# 2026-08-26 회귀 — 나스닥 스크리너가 `download=true`(평면 data.rows)를 더 이상
# 채워주지 않고(HTTP 200 + rows:null), `exchange=nasdaq,nyse,amex`처럼 콤마로 이은
# 거래소 목록도 0행을 준다. 살아있는 형태는 `data.table.rows`다.
TABLE_RESPONSE = {
    "data": {
        "filters": None,
        "table": {
            "headers": {"symbol": "Symbol", "name": "Name", "marketCap": "Market Cap"},
            "rows": [
                {"symbol": "NVDA", "name": "NVIDIA Corporation Common Stock",
                 "lastsale": "$213.05", "marketCap": "5,155,810,000,000"},
                {"symbol": "AAPL", "name": "Apple Inc. Common Stock",
                 "lastsale": "$250.00", "marketCap": "3,400,000,000,000"},
            ],
        },
    },
    "status": {"rCode": 200},
}


def test_fetch_us_universe_parses_table_rows():
    """현행 응답 형태(data.table.rows)를 읽는다."""
    with mock.patch('src.data.us_universe.requests.get') as m:
        m.return_value.json.return_value = TABLE_RESPONSE
        m.return_value.raise_for_status = lambda: None
        rows = fetch_us_universe(limit=10)
    assert [r['symbol'] for r in rows] == ['NVDA', 'AAPL']
    # 콤마가 든 시총 문자열도 숫자로 읽어야 한다.
    assert rows[0]['market_cap'] == 5155810000000.0


def test_fetch_us_universe_request_avoids_dead_params():
    """죽은 파라미터를 보내지 않는다 — download=true, 콤마로 이은 exchange."""
    with mock.patch('src.data.us_universe.requests.get') as m:
        m.return_value.json.return_value = TABLE_RESPONSE
        m.return_value.raise_for_status = lambda: None
        fetch_us_universe(limit=10)
    params = m.call_args.kwargs['params']
    assert params.get('download') != 'true'
    assert ',' not in params.get('exchange', '')
    # 정렬은 유지돼야 한다 — 없으면 limit이 "시총 상위 N"이 아니게 된다.
    assert params['sortColumn'] == 'marketcap' and params['sortOrder'] == 'desc'


# ── 소프트 차단 ─────────────────────────────────────────────────────
# 2026-08-24·25에 us_eod_watchlist가 이걸로 죽어 미국 워치리스트가 이틀 결손이었다.
# HTTP 200에 rows만 비어 오는 형태라 raise_for_status로는 안 걸린다.
# 미국 심 3개가 그 세션을 통째로 잃는다 — 한 번 실패에 포기하면 안 된다.
EMPTY = {'data': {'table': {'rows': []}}}
FILLED = {'data': {'table': {'rows': [
    {'symbol': 'AAPL', 'name': 'Apple', 'marketCap': '1000'}]}}}


def test_빈_응답이면_재시도한다():
    with mock.patch('src.data.us_universe.requests.get') as m,          mock.patch('src.data.us_universe.time.sleep'):
        m.return_value.raise_for_status = lambda: None
        m.return_value.json.side_effect = [EMPTY, EMPTY, FILLED]
        rows = fetch_us_universe(limit=10)
    assert m.call_count == 3, '재시도하지 않았다'
    assert rows[0]['symbol'] == 'AAPL'


def test_재시도가_유한하고_결국_예외다():
    with mock.patch('src.data.us_universe.requests.get') as m,          mock.patch('src.data.us_universe.time.sleep'):
        m.return_value.raise_for_status = lambda: None
        m.return_value.json.return_value = EMPTY
        try:
            fetch_us_universe(limit=10)
            assert False, '예외가 나야 한다'
        except RuntimeError:
            pass
    assert m.call_count == us_universe.SOFT_BLOCK_RETRIES


def test_HTTP_오류는_재시도하지_않는다():
    """소프트 차단(200+빈행)과 진짜 오류는 다르다. 4xx를 재시도하면 차단만 깊어진다."""
    with mock.patch('src.data.us_universe.requests.get') as m,          mock.patch('src.data.us_universe.time.sleep'):
        m.return_value.raise_for_status.side_effect = Exception('403')
        try:
            fetch_us_universe(limit=10)
            assert False, '예외가 나야 한다'
        except Exception:
            pass
    assert m.call_count == 1
