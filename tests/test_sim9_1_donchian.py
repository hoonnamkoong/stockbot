import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.strategy.simulators.sim9_1_donchian import POSITION_WEIGHT, decide_donchian, MIN_SAMPLE

# 20일 채널: 저점 900, 상단 1000
CHANNEL = [900 + (i % 5) * 25 for i in range(19)] + [1000]


def _view(portfolio, nav=3_000_000):
    return {'portfolio': portfolio, 'cash': nav, 'initial_cash': 3_000_000, 'nav': nav,
            'cooldown_codes': {}, 'market_index_healthy': True}


def _filler(n=MIN_SAMPLE + 2, amount=1_500_000_000):
    """거래대금 z 표본을 채우는 종목들. 채널 이력이 없어 진입 후보는 아니다."""
    return [{'code': f'F{i:03d}', 'name': f'중립{i}', 'price': 1000, 'amount': amount,
             'range_history': []} for i in range(n)]


def _target(**kw):
    s = {'code': 'T001', 'name': '돌파주', 'price': 1050, 'amount': 50_000_000_000,
         'range_history': list(CHANNEL)}
    s.update(kw)
    return s


def _buys(o):
    return [x for x in o if x['action'] == 'BUY']


def _sells(o):
    return [x for x in o if x['action'] == 'SELL']


# ── 진입 ────────────────────────────────────────────────
def test_breakout_entry():
    orders = decide_donchian(_view({}), [_target()] + _filler(), {'T001': 1050})
    b = [o for o in _buys(orders) if o['code'] == 'T001']
    assert len(b) == 1 and '채널 돌파' in b[0]['reason']


def test_no_entry_inside_channel():
    """채널 안이면 돌파가 아니다 — 상단과 같아도 진입하지 않는다."""
    orders = decide_donchian(_view({}), [_target(price=1000)] + _filler(), {'T001': 1000})
    assert [o for o in _buys(orders) if o['code'] == 'T001'] == []


def test_no_entry_without_volume_confirmation():
    """거래대금 z <= 0이면 돌파를 믿지 않는다."""
    cands = [_target(amount=1_500_000_000)] + _filler(amount=50_000_000_000)
    orders = decide_donchian(_view({}), cands, {'T001': 1050})
    assert [o for o in _buys(orders) if o['code'] == 'T001'] == []


def test_no_entry_with_short_history():
    """20일 이력이 없으면 채널을 만들지 않는다 — 이게 심9-1이 검증을 기다리는 이유다."""
    orders = decide_donchian(_view({}), [_target(range_history=CHANNEL[:12])] + _filler(),
                             {'T001': 1050})
    assert [o for o in _buys(orders) if o['code'] == 'T001'] == []


def test_no_entry_when_illiquid():
    orders = decide_donchian(_view({}), [_target(amount=500_000_000)] + _filler(),
                             {'T001': 1050})
    assert [o for o in _buys(orders) if o['code'] == 'T001'] == []


def test_no_signal_when_sample_too_thin():
    orders = decide_donchian(_view({}), [_target()] + _filler(3), {'T001': 1050})
    assert _buys(orders) == []


def test_entry_takes_full_weight():
    orders = decide_donchian(_view({}), [_target()] + _filler(), {'T001': 1050})
    b = [o for o in _buys(orders) if o['code'] == 'T001'][0]
    assert b['quantity'] == int(3_000_000 * POSITION_WEIGHT / 1050)


# ── 청산 ────────────────────────────────────────────────
def _held(avg=1050):
    return {'T001': {'name': '돌파주', 'quantity': 10, 'avg_price': avg, 'peak_price': avg}}


def test_exit_below_10day_channel_low():
    """수익 중이라 10일 저점이 진입가 위로 올라온 상태 — 이때 채널 청산이 이익을 잠근다.
    (진입 직후 손실 구간에서는 2*ATR 손절이 항상 먼저 걸린다.)"""
    rising = [1000 + 10 * i for i in range(20)]      # 10일 저점 1100, ATR 10 → 손절 980
    orders = decide_donchian(_view(_held(avg=1000)),
                             [_target(price=1090, range_history=rising)], {'T001': 1090})
    s = _sells(orders)
    assert len(s) == 1 and '채널 이탈' in s[0]['reason']


def test_atr_stop_fires_before_channel_exit():
    """급락은 채널 저점에 닿기 전에 2*ATR 손절이 먼저 잡는다."""
    orders = decide_donchian(_view(_held(avg=1050)), [_target(price=920)], {'T001': 920})
    s = _sells(orders)
    assert len(s) == 1 and 'ATR 손절' in s[0]['reason']


def test_no_fixed_take_profit():
    """터틀은 추세를 끝까지 탄다 — 고정 익절 없음."""
    orders = decide_donchian(_view(_held()), [_target(price=1400)], {'T001': 1400})
    assert _sells(orders) == []


def test_holding_absent_from_candidates_is_not_touched():
    """오늘 후보에 없으면 채널을 계산할 수 없다 — 없는 근거로 팔지 않는다."""
    orders = decide_donchian(_view({'ZZZ': {'name': 'x', 'quantity': 10, 'avg_price': 1000,
                                            'peak_price': 1000}}), _filler(), {'ZZZ': 500})
    assert _sells(orders) == []
