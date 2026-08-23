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
