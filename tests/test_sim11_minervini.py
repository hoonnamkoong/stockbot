import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators.sim11_minervini import (
    POSITION_WEIGHT, STOP_PCT, decide_minervini, _sma, _trend_template_ok, _vcp_breakout,
)


def _view(portfolio, nav=3_000_000):
    return {'portfolio': portfolio, 'cash': nav, 'initial_cash': 3_000_000, 'nav': nav,
            'cooldown_codes': {}, 'market_index_healthy': True}


def _rising_closes(n=200, start=100.0, step=0.5):
    """단조 증가 종가열. 어떤 구간을 잘라도 최근 평균이 과거 평균보다 높다 —
    MA50>MA150>MA200·MA200 상승추세가 자동으로 성립한다."""
    return [start + i * step for i in range(n)]


def _good_closes():
    """추세 템플릿 + VCP 압축을 둘 다 만족하는 220일 종가열(당일 미포함).

    0~199일: 완만한 상승(100→199.5) — 정배열·MA200 상승추세 재료.
    200~209일(그 이전 10일): 199.5~201.5 사이 넓게 진동 — 압축 '이전' 구간.
    210~219일(최근 10일): 201.0~201.3 사이 좁게 진동 — VCP 압축 구간.
    """
    base = _rising_closes(200, start=100.0, step=0.5)      # 100.0 ~ 199.5
    prior_tail = [199.5 + (i % 2) * 2.0 for i in range(10)]   # 199.5~201.5, 변동폭 2.0
    recent_tail = [201.0 + (i % 2) * 0.3 for i in range(10)]  # 201.0~201.3, 변동폭 0.3(압축)
    return base + prior_tail + recent_tail


GOOD_CLOSES = _good_closes()
GOOD_PRICE = 205.0     # 최근 20일 고점(201.5) 돌파
GOOD_W52_LWPR = 90.0   # price(205) >= 90*1.3=117 충족
GOOD_W52_HGPR = 210.0  # price(205) >= 210*0.75=157.5 충족
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


def test_vcp_breakout_on_good_setup():
    assert _vcp_breakout(GOOD_PRICE, GOOD_CLOSES) is True


def test_vcp_no_breakout_inside_pivot():
    """최근 20일 고점을 못 넘으면 압축돼 있어도 진입 신호가 아니다."""
    assert _vcp_breakout(199.0, GOOD_CLOSES) is False


def test_vcp_no_contraction_no_signal():
    """돌파해도 직전 변동폭이 안 줄었으면(압축 없이 그냥 상승) VCP가 아니다."""
    wide_tail_closes = _rising_closes(200) + [190 + (i % 2) * 20 for i in range(20)]  # 변동폭 20
    assert _vcp_breakout(215.0, wide_tail_closes) is False


# ── decide_minervini: 진입 ──────────────────────────────
def test_entry_when_all_gates_pass():
    orders = decide_minervini(_view({}), [_stock()], {'T001': GOOD_PRICE})
    b = _buys(orders)
    assert len(b) == 1 and 'VCP 돌파' in b[0]['reason']


def test_no_entry_without_earnings_acceleration():
    orders = decide_minervini(_view({}), [_stock(eps_growth_yoy=5.0)], {'T001': GOOD_PRICE})
    assert _buys(orders) == []


def test_no_entry_when_eps_growth_missing():
    """조회 실패로 결손이면 산다는 근거가 없다 — 게이트를 통과시키지 않는다."""
    orders = decide_minervini(_view({}), [_stock(eps_growth_yoy=None)], {'T001': GOOD_PRICE})
    assert _buys(orders) == []


def test_no_entry_without_revenue_growth():
    orders = decide_minervini(_view({}), [_stock(revenue_growth_yoy=5.0)], {'T001': GOOD_PRICE})
    assert _buys(orders) == []


def test_no_entry_when_trend_template_fails():
    orders = decide_minervini(_view({}), [_stock(price=100.0)], {'T001': 100.0})
    assert _buys(orders) == []


def test_no_entry_when_illiquid():
    orders = decide_minervini(_view({}), [_stock(amount=500_000_000)], {'T001': GOOD_PRICE})
    assert _buys(orders) == []


def test_entry_takes_full_position_weight():
    orders = decide_minervini(_view({}), [_stock()], {'T001': GOOD_PRICE})
    b = _buys(orders)[0]
    assert b['quantity'] == int(3_000_000 * POSITION_WEIGHT / GOOD_PRICE)


def test_max_holdings_caps_entries():
    stocks = [_stock(code=f'T{i:03d}') for i in range(7)]
    prices = {s['code']: GOOD_PRICE for s in stocks}
    orders = decide_minervini(_view({}), stocks, prices)
    assert len(_buys(orders)) == 5   # MAX_HOLDINGS


# ── decide_minervini: 청산 ──────────────────────────────
def _held(avg=GOOD_PRICE):
    return {'T001': {'name': '추세주', 'quantity': 10, 'avg_price': avg, 'peak_price': avg}}


def test_hard_stop_fires():
    avg = 1000.0
    stop_price = avg * (1 + STOP_PCT / 100) - 1
    orders = decide_minervini(_view(_held(avg=avg)), [_stock(price=stop_price)],
                              {'T001': stop_price})
    s = _sells(orders)
    assert len(s) == 1 and '손절' in s[0]['reason']


def test_exit_below_50day_ma():
    """MA50 아래로 종가가 내려오면 추세 종료로 보고 판다 — 손실이 아니어도."""
    ma50 = _sma(GOOD_CLOSES, 50)
    below_ma = ma50 - 1
    orders = decide_minervini(_view(_held(avg=150.0)), [_stock(price=below_ma)],
                              {'T001': below_ma})
    s = _sells(orders)
    assert len(s) == 1 and '50일선 이탈' in s[0]['reason']


def test_no_fixed_take_profit():
    """미너비니 철학 — 승자는 끝까지 탄다. 고정 익절 없음."""
    far_above = GOOD_CLOSES[-1] * 2
    orders = decide_minervini(_view(_held(avg=150.0)), [_stock(price=far_above)],
                              {'T001': far_above})
    assert _sells(orders) == []


def test_holding_absent_from_candidates_is_not_touched():
    """오늘 후보에 없으면 50일선을 계산할 수 없다 — 손절폭 밖이면 없는 근거로
    팔지 않는다(하드손절은 가격만으로 판단하므로 여기서는 손절선 밖의 등락만 준다)."""
    orders = decide_minervini(
        _view({'ZZZ': {'name': 'x', 'quantity': 10, 'avg_price': 100, 'peak_price': 100}}),
        [], {'ZZZ': 98})
    assert _sells(orders) == []
