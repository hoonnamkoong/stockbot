import os, sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators import sim11_minervini as sim11
from src.strategy.simulators.sim11_minervini import (
    POSITION_WEIGHT, STOP_PCT, decide_minervini, build_watchlist_entry,
    save_watchlist, load_watchlist, _sma, _trend_template_ok, _vcp_contracting,
)


def _view(portfolio, nav=3_000_000):
    return {'portfolio': portfolio, 'cash': nav, 'initial_cash': 3_000_000, 'nav': nav,
            'cooldown_codes': {}, 'market_index_healthy': True}


def _rising_closes(n=200, start=100.0, step=0.5):
    """단조 증가 종가열. 어떤 구간을 잘라도 최근 평균이 과거 평균보다 높다 —
    MA50>MA150>MA200·MA200 상승추세가 자동으로 성립한다."""
    return [start + i * step for i in range(n)]


def _good_closes():
    """추세 템플릿 + VCP 압축을 둘 다 만족하는 220일 종가열(오늘 미포함).

    0~199일: 완만한 상승(100→199.5) — 정배열·MA200 상승추세 재료.
    200~209일(그 이전 10일): 199.5~201.5 사이 넓게 진동 — 압축 '이전' 구간.
    210~219일(최근 10일): 201.0~201.3 사이 좁게 진동 — VCP 압축 구간.
    """
    base = _rising_closes(200, start=100.0, step=0.5)      # 100.0 ~ 199.5
    prior_tail = [199.5 + (i % 2) * 2.0 for i in range(10)]   # 199.5~201.5, 변동폭 2.0
    recent_tail = [201.0 + (i % 2) * 0.3 for i in range(10)]  # 201.0~201.3, 변동폭 0.3(압축)
    return base + prior_tail + recent_tail


GOOD_CLOSES = _good_closes()          # 오늘 미포함(어제까지)
GOOD_PRICE = 201.2                    # 오늘 종가 — 감시목록 계산엔 이게 마지막 구간에 들어간다
GOOD_W52_LWPR = 90.0                  # price(201.2) >= 90*1.3=117 충족
GOOD_W52_HGPR = 210.0                 # price(201.2) >= 210*0.75=157.5 충족
GOOD_EPS_G = 25.0
GOOD_REV_G = 20.0


def _stock(**kw):
    s = {'code': 'T001', 'name': '추세주', 'price': GOOD_PRICE, 'amount': 50_000_000_000,
         'daily_closes': list(GOOD_CLOSES), 'w52_hgpr': GOOD_W52_HGPR, 'w52_lwpr': GOOD_W52_LWPR,
         'eps_growth_yoy': GOOD_EPS_G, 'revenue_growth_yoy': GOOD_REV_G}
    s.update(kw)
    return s


def _buys(o):
    return [x for x in o if x['action'] == 'BUY']


def _sells(o):
    return [x for x in o if x['action'] == 'SELL']


# ── 순수 헬퍼 ────────────────────────────────────────────
def test_sma_needs_full_window():
    assert _sma([1.0, 2.0, 3.0], 5) is None
    assert _sma([1.0, 2.0, 3.0, 4.0, 5.0], 5) == 3.0


def test_trend_template_passes_on_good_setup():
    assert _trend_template_ok(GOOD_PRICE, GOOD_CLOSES, GOOD_W52_HGPR, GOOD_W52_LWPR) is True


def test_trend_template_fails_below_ma50():
    assert _trend_template_ok(100.0, GOOD_CLOSES, GOOD_W52_HGPR, GOOD_W52_LWPR) is False


def test_trend_template_fails_too_close_to_52w_low():
    """52주 저가 대비 30% 미만 상승이면 아직 바닥권 — 추세 초입이 아니다."""
    assert _trend_template_ok(GOOD_PRICE, GOOD_CLOSES, GOOD_W52_HGPR, w52_lwpr=180.0) is False


def test_trend_template_fails_too_far_below_52w_high():
    assert _trend_template_ok(GOOD_PRICE, GOOD_CLOSES, w52_hgpr=1000.0, w52_lwpr=GOOD_W52_LWPR) is False


def test_trend_template_fails_with_short_history():
    """200+20일 미만이면 MA200 상승추세를 확인할 과거 시점이 없다."""
    assert _trend_template_ok(GOOD_PRICE, GOOD_CLOSES[-210:], GOOD_W52_HGPR, GOOD_W52_LWPR) is False


def test_vcp_contracting_on_good_setup():
    assert _vcp_contracting(GOOD_CLOSES + [GOOD_PRICE]) is True


def test_vcp_no_contraction_when_recent_range_is_not_narrower():
    wide_tail = _rising_closes(200) + [190 + (i % 2) * 20 for i in range(20)]  # 변동폭 20, 안 줄어듦
    assert _vcp_contracting(wide_tail) is False


def test_vcp_needs_enough_history():
    assert _vcp_contracting([100.0] * 15) is False


# ── build_watchlist_entry ────────────────────────────────
def test_watchlist_entry_built_on_good_setup():
    e = build_watchlist_entry(_stock())
    assert e is not None
    assert e['name'] == '추세주'
    closes_through_today = GOOD_CLOSES + [GOOD_PRICE]
    assert e['pivot_price'] == max(closes_through_today[-20:])
    assert e['ma50'] == _sma(closes_through_today, 50)


def test_watchlist_entry_none_without_earnings_acceleration():
    assert build_watchlist_entry(_stock(eps_growth_yoy=5.0)) is None


def test_watchlist_entry_none_when_eps_growth_missing():
    """조회 실패로 결손이면 등재 근거가 없다."""
    assert build_watchlist_entry(_stock(eps_growth_yoy=None)) is None


def test_watchlist_entry_none_without_revenue_growth():
    assert build_watchlist_entry(_stock(revenue_growth_yoy=5.0)) is None


def test_watchlist_entry_none_when_trend_template_fails():
    assert build_watchlist_entry(_stock(price=100.0)) is None


def test_watchlist_entry_none_when_not_contracting():
    wide_tail = _rising_closes(200) + [190 + (i % 2) * 20 for i in range(19)]
    assert build_watchlist_entry(_stock(price=210.0, daily_closes=wide_tail)) is None


# ── save_watchlist / load_watchlist ──────────────────────
def test_watchlist_round_trips_for_the_same_date(tmp_path):
    path = str(tmp_path / 'w.json')
    with mock.patch.object(sim11, 'WATCHLIST_PATH', path):
        save_watchlist({'T001': {'name': '추세주', 'pivot_price': 200.0, 'ma50': 150.0}}, '20260820')
        loaded = load_watchlist('20260820')
    assert loaded == {'T001': {'name': '추세주', 'pivot_price': 200.0, 'ma50': 150.0}}


def test_watchlist_rejects_stale_date(tmp_path):
    """날짜가 다르면 빈 감시목록이다 — 낡은 pivot으로 잘못된 시점에 사면 안 된다."""
    path = str(tmp_path / 'w.json')
    with mock.patch.object(sim11, 'WATCHLIST_PATH', path):
        save_watchlist({'T001': {'name': 'x', 'pivot_price': 1.0, 'ma50': 1.0}}, '20260819')
        loaded = load_watchlist('20260820')
    assert loaded == {}


def test_missing_watchlist_file_returns_empty(tmp_path):
    path = str(tmp_path / '없음.json')
    with mock.patch.object(sim11, 'WATCHLIST_PATH', path):
        assert load_watchlist('20260820') == {}


# ── decide_minervini: 진입(실시간가가 pivot을 넘어야 한다) ─
def _watch_stock(**kw):
    s = {'code': 'T001', 'name': '추세주', 'price': 210.0, 'amount': 50_000_000_000,
         'pivot_price': 200.0, 'ma50': 150.0}
    s.update(kw)
    return s


def test_entry_when_price_crosses_pivot_live():
    orders = decide_minervini(_view({}), [_watch_stock()], {'T001': 210.0})
    b = _buys(orders)
    assert len(b) == 1 and 'pivot' in b[0]['reason']


def test_no_entry_when_price_has_not_reached_pivot():
    orders = decide_minervini(_view({}), [_watch_stock(price=199.0)], {'T001': 199.0})
    assert _buys(orders) == []


def test_no_entry_exactly_at_pivot():
    """같아도 돌파가 아니다 — 초과해야 한다."""
    orders = decide_minervini(_view({}), [_watch_stock(price=200.0)], {'T001': 200.0})
    assert _buys(orders) == []


def test_no_entry_when_illiquid():
    orders = decide_minervini(_view({}), [_watch_stock(amount=500_000_000)], {'T001': 210.0})
    assert _buys(orders) == []


def test_no_entry_without_pivot_price():
    """감시목록에 없는(pivot_price 결손) 종목은 자격이 없다."""
    orders = decide_minervini(_view({}), [_watch_stock(pivot_price=None)], {'T001': 210.0})
    assert _buys(orders) == []


def test_entry_takes_full_position_weight():
    orders = decide_minervini(_view({}), [_watch_stock()], {'T001': 210.0})
    b = _buys(orders)[0]
    assert b['quantity'] == int(3_000_000 * POSITION_WEIGHT / 210.0)


def test_max_holdings_caps_entries():
    stocks = [_watch_stock(code=f'T{i:03d}') for i in range(7)]
    prices = {s['code']: 210.0 for s in stocks}
    orders = decide_minervini(_view({}), stocks, prices)
    assert len(_buys(orders)) == 5   # MAX_HOLDINGS


# ── decide_minervini: 청산 ──────────────────────────────
def _held(avg=210.0):
    return {'T001': {'name': '추세주', 'quantity': 10, 'avg_price': avg, 'peak_price': avg}}


def test_hard_stop_fires():
    avg = 1000.0
    stop_price = avg * (1 + STOP_PCT / 100) - 1
    orders = decide_minervini(_view(_held(avg=avg)), [_watch_stock(price=stop_price)],
                              {'T001': stop_price})
    s = _sells(orders)
    assert len(s) == 1 and '손절' in s[0]['reason']


def test_exit_below_50day_ma():
    """MA50(감시목록 값) 아래로 실시간가가 내려오면 판다 — 하드손절 폭 안쪽이어도."""
    below_ma = 149.0   # ma50=150
    orders = decide_minervini(_view(_held(avg=155.0)), [_watch_stock(price=below_ma)],
                              {'T001': below_ma})
    s = _sells(orders)
    assert len(s) == 1 and '50일선 이탈' in s[0]['reason']


def test_no_fixed_take_profit():
    """미너비니 철학 — 승자는 끝까지 탄다. 고정 익절 없음."""
    far_above = 1000.0
    orders = decide_minervini(_view(_held(avg=180.0)), [_watch_stock(price=far_above)],
                              {'T001': far_above})
    assert _sells(orders) == []


def test_holding_absent_from_candidates_is_not_touched():
    """오늘 후보에 없으면 ma50을 알 수 없다 — 손절폭 밖이면 없는 근거로 팔지 않는다."""
    orders = decide_minervini(
        _view({'ZZZ': {'name': 'x', 'quantity': 10, 'avg_price': 100, 'peak_price': 100}}),
        [], {'ZZZ': 98})
    assert _sells(orders) == []


# ── get_universe: 오늘자 감시목록만 쓴다 ───────────────────
def test_get_universe_returns_watchlist_without_price():
    """price는 여기서 안 채운다 — _enrich_universe가 실시간 KIS 시세로 채운다."""
    from src.strategy.simulators.sim11_minervini import MinerviniTrendSimulator
    sim = object.__new__(MinerviniTrendSimulator)
    today = sim11.get_kst_now().strftime('%Y%m%d')
    with mock.patch.object(sim11, 'load_watchlist',
                           return_value={'T001': {'name': '추세주', 'pivot_price': 200.0, 'ma50': 150.0}}):
        universe = sim.get_universe()
    assert universe == [{'code': 'T001', 'name': '추세주', 'pivot_price': 200.0, 'ma50': 150.0}]
    assert 'price' not in universe[0]


def test_get_universe_empty_without_todays_watchlist():
    from src.strategy.simulators.sim11_minervini import MinerviniTrendSimulator
    sim = object.__new__(MinerviniTrendSimulator)
    with mock.patch.object(sim11, 'load_watchlist', return_value={}):
        assert sim.get_universe() == []
