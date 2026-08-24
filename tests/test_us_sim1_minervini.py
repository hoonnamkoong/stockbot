import datetime as dt
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
    candidates = [{'symbol': 'AAPL', 'price': 205.0, 'avg_dollar_volume': 50_000_000,
                   'pivot_price': 200.0, 'ma50': 190.0, 'name': 'Apple'}]
    # decide_us_minervini는 candidates에서 'code' 키를 읽는다 — get_universe()가
    # 'symbol'을 'code'로 옮겨 준다(Sim11의 KIS 'code' 관례와 맞춘다).
    candidates[0]['code'] = candidates[0].pop('symbol')
    orders = m.decide_us_minervini(view, candidates, {'AAPL': 205.0})
    assert len(orders) == 1
    assert orders[0]['action'] == 'BUY'
    assert orders[0]['code'] == 'AAPL'
    assert orders[0]['quantity'] == int(20000.0 * 0.19 / 205.0)


def test_decide_us_minervini_no_entry_when_illiquid():
    """유동성 문턱은 실시간 amount가 아니라 워치리스트의 avg_dollar_volume(EOD 평균
    거래대금)으로 판정한다 — 개장 직후 당일 누적 거래량이 작아 실제로는 유동성이
    충분한 종목의 진입이 막히는 문제를 피하기 위함(2026-08-24 리뷰에서 발견)."""
    view = {'portfolio': {}, 'nav': 20000.0, 'cooldown_codes': {}}
    candidates = [{'code': 'AAPL', 'price': 205.0, 'avg_dollar_volume': 1.0,
                   'pivot_price': 200.0, 'ma50': 190.0, 'name': 'Apple'}]
    orders = m.decide_us_minervini(view, candidates, {'AAPL': 205.0})
    assert orders == []


def test_us_minervini_simulator_get_universe_reads_todays_watchlist(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'WATCHLIST_PATH', str(tmp_path / 'wl.json'))
    m.save_watchlist({'AAPL': {'name': 'Apple', 'pivot_price': 200.0, 'ma50': 190.0,
                                'avg_dollar_volume': 50_000_000}},
                      m.us_trading_date())
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
    assert universe == [{'code': 'AAPL', 'name': 'Apple', 'pivot_price': 200.0, 'ma50': 190.0,
                          'avg_dollar_volume': 50_000_000}]


# ── us_calendar 재노출 확인 ────────────────────────────────────────────
# 날짜 경계 로직 자체의 상세 테스트는 tests/test_us_calendar.py로 옮겼다(다른
# US 심도 같은 모듈을 쓴다). 여기서는 이 모듈의 이름으로도 여전히 접근되는지만 본다.

def _utc(y, mo, d, h, mi=0):
    return dt.datetime(y, mo, d, h, mi, tzinfo=dt.timezone.utc)


def test_calendar_functions_still_reachable_via_this_module():
    from src.strategy.simulators import us_calendar
    assert m.us_trading_date is us_calendar.us_trading_date
    assert m.next_us_trading_date is us_calendar.next_us_trading_date
    assert m.next_us_trading_date(_utc(2026, 8, 24, 22)) == '20260825'
