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
