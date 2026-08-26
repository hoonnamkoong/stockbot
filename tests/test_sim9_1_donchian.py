import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.strategy.simulators.sim9_1_donchian import POSITION_WEIGHT, decide_donchian, MIN_SAMPLE

# 20일 채널: 저점 900, 상단 1000
CHANNEL = [900 + (i % 5) * 25 for i in range(19)] + [1000]


def _view(portfolio, nav=3_000_000):
    return {'portfolio': portfolio, 'cash': nav, 'initial_cash': 3_000_000, 'nav': nav,
            'cooldown_codes': {}, 'market_index_healthy': True}


def _filler(n=MIN_SAMPLE + 2, amount=1_500_000_000):
    """거래대금 z 표본을 채우는 종목들. 채널 이력이 없어 진입 후보는 아니다.

    amount_history를 amount와 같게 둬서 '평소대로 도는' 배경(급증 배수 1.0)을
    만든다 — 급증은 절대 거래대금이 아니라 자기 평균 대비로 재기 때문이다."""
    return [{'code': f'F{i:03d}', 'name': f'중립{i}', 'price': 1000, 'amount': amount,
             'range_history': [], 'amount_history': [amount] * 20} for i in range(n)]


def _target(**kw):
    # amount는 amount_history 평균(100억)의 5배 — 돌파에 거래대금이 동반된 상태.
    # 절대값이 아니라 자기 평균 대비 배수로 판정한다.
    s = {'code': 'T001', 'name': '돌파주', 'price': 1050, 'amount': 50_000_000_000,
         'range_history': list(CHANNEL), 'amount_history': [10_000_000_000] * 20}
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
    """자기 평균 대비 배수가 배경보다 낮으면(z<=0) 돌파를 믿지 않는다."""
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


# 2026-08-26 — 미국판(US Sim2)에서 실측으로 드러난 결함이 여기에도 그대로 있다.
# `zamt > 0`이 **절대 거래대금의 횡단면 z**라서, 게이트 이름은 "거래대금 동반(급증)"
# 인데 실제로는 "다른 종목보다 큰가" = 대형주 필터로 동작한다. 미국 후보 300종목
# 실측에서 20일 채널을 돌파한 16종목이 전부 이 게이트에서 막혔다.
# 급증은 그 종목 **자신의 평균 대비**로 재야 한다(amount_history가 기준선).

def _surge_filler(n=MIN_SAMPLE + 2, amount=1_500_000_000):
    """평소대로 도는 배경 종목(급증 배수 1.0)."""
    return [{'code': f'F{i:03d}', 'name': f'중립{i}', 'price': 1000, 'amount': amount,
             'range_history': [], 'amount_history': [amount] * 20} for i in range(n)]


def test_breakout_with_own_volume_surge_is_bought():
    """절대 거래대금이 배경보다 작아도 자기 평균 대비 급증했으면 산다."""
    target = _target(amount=3_000_000_000, amount_history=[1_000_000_000] * 20)  # 3배
    orders = decide_donchian(_view({}), [target] + _surge_filler(), {'T001': 1050})
    assert [o['code'] for o in _buys(orders)] == ['T001']


def test_breakout_without_own_volume_surge_is_skipped():
    """평소만큼만 도는 돌파는 '거래대금 동반'이 아니다."""
    target = _target(amount=1_000_000_000, amount_history=[10_000_000_000] * 20)  # 0.1배
    orders = decide_donchian(_view({}), [target] + _surge_filler(), {'T001': 1050})
    assert _buys(orders) == []


def test_size_alone_no_longer_passes_the_gate():
    """거래대금 절대값만 크고 자기 평균대로 도는 종목은 통과하지 못한다 —
    이게 옛 게이트가 실제로 재던 것이다."""
    target = _target(amount=50_000_000_000, amount_history=[50_000_000_000] * 20)  # 1.0배
    orders = decide_donchian(_view({}), [target] + _surge_filler(), {'T001': 1050})
    assert _buys(orders) == []


def test_unmeasured_baseline_is_not_treated_as_surge():
    """거래대금 이력이 없는 종목은 급증 판정에서 뺀다 — '측정 불가'를 '급증'으로
    바꾸지 않는다(스크래퍼가 amount_history를 아직 안 싣는 구간의 방어선)."""
    target = _target(amount=3_000_000_000)   # amount_history 없음
    orders = decide_donchian(_view({}), [target] + _surge_filler(), {'T001': 1050})
    assert _buys(orders) == []
