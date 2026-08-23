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
