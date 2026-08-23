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
