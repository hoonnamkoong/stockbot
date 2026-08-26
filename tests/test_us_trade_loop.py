import datetime as dt
from zoneinfo import ZoneInfo
from unittest import mock

from scripts.us_trade_loop import is_us_market_open, main, run_cycle


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


# 2026-08-26 — EOD 배치가 이틀 연속 죽어 워치리스트가 아예 없었는데도 이 루프는
# 5분마다 "N개 심 실행 완료"를 초록으로 찍었다. 후보 0개와 "오늘은 살 게 없다"가
# 로그에서 구분되지 않아 매매 0건이 이틀 동안 정상으로 보였다.

class _EmptySim:
    def __init__(self, name='EmptyUs'):
        self.name = name
        self.state = {'portfolio': {}}

    def get_universe(self):
        return []

    def run(self, candidates, current_prices):
        pass


def test_run_cycle_returns_candidate_count_per_sim():
    """로그가 심별 후보 수를 말할 수 있어야 한다."""
    sim, empty = _FakeSim(), _EmptySim()
    quotes = {'AAPL': {'price': 205.0, 'volume': 1000}, 'TSLA': {'price': 190.0, 'volume': 500}}
    counts = run_cycle([sim, empty], mock.Mock(side_effect=lambda s: quotes.get(s)))
    assert counts == {'FakeUs': 1, 'EmptyUs': 0}


def test_main_alerts_when_every_sim_has_no_candidates():
    """전 심 후보 0 = 워치리스트 결손. EOD 배치가 안 돌았다는 뜻이다."""
    with mock.patch('scripts.us_trade_loop.is_us_market_open', return_value=True), \
         mock.patch('scripts.us_trade_loop.get_active_us_simulators',
                    return_value=[_EmptySim('A'), _EmptySim('B')]), \
         mock.patch('scripts.us_trade_loop.fetch_current_quote'), \
         mock.patch('scripts.us_trade_loop.alerts.send_alert_once') as alert:
        main()
    assert alert.called, '결손인데 조용히 넘어갔다'
    assert 'A' in alert.call_args.args[1] and 'B' in alert.call_args.args[1]


def test_main_does_not_alert_when_any_sim_has_candidates():
    """한 심이라도 후보가 있으면 배치는 돈 것 — 나머지 0은 정상 결과다."""
    quotes = {'AAPL': {'price': 205.0, 'volume': 1000}, 'TSLA': {'price': 190.0, 'volume': 500}}
    with mock.patch('scripts.us_trade_loop.is_us_market_open', return_value=True), \
         mock.patch('scripts.us_trade_loop.get_active_us_simulators',
                    return_value=[_FakeSim(), _EmptySim()]), \
         mock.patch('scripts.us_trade_loop.fetch_current_quote',
                    side_effect=lambda s: quotes.get(s)), \
         mock.patch('scripts.us_trade_loop.alerts.send_alert_once') as alert:
        main()
    assert not alert.called


def test_main_does_not_alert_when_market_closed():
    """휴장에 심이 0개인 건 결손이 아니다."""
    with mock.patch('scripts.us_trade_loop.is_us_market_open', return_value=False), \
         mock.patch('scripts.us_trade_loop.alerts.send_alert_once') as alert:
        main()
    assert not alert.called
