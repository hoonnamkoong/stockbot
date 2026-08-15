import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.strategy.simulators.sim8_accumulation import POSITION_WEIGHT, decide_accumulation, MIN_SAMPLE


def _view(portfolio, nav=3_000_000):
    return {'portfolio': portfolio, 'cash': nav, 'initial_cash': 3_000_000, 'nav': nav,
            'cooldown_codes': {}, 'market_index_healthy': True}


def _filler(n=MIN_SAMPLE + 2):
    """z-score 표본을 채우는 중립 종목들. 정보축·군중축 모두 평범하게 둔다."""
    out = []
    for i in range(n):
        out.append({'code': f'F{i:03d}', 'name': f'중립{i}', 'price': 1000,
                    'amount': 2_000_000_000, 'w52_hgpr': 2000, 'w52_lwpr': 500,
                    'frgn_fake_ntby_qty': i, 'orgn_fake_ntby_qty': -i,
                    'foreign_change': 0.01 * i, 'unique_posters': 50 + i})
    return out


def _target(**kw):
    """기본값 = 매집 진입 조건 충족 (52주 90%, 정보축 극단, 군중 미달)"""
    s = {'code': 'T001', 'name': '매집주', 'price': 900, 'amount': 5_000_000_000,
         'w52_hgpr': 1000, 'w52_lwpr': 400,
         'frgn_fake_ntby_qty': 5_000_000, 'orgn_fake_ntby_qty': 3_000_000,
         'foreign_change': 5.0, 'unique_posters': 1}
    s.update(kw)
    return s


def _buys(orders):
    return [o for o in orders if o['action'] == 'BUY']


def _sells(orders):
    return [o for o in orders if o['action'] == 'SELL']


# ── 진입 ────────────────────────────────────────────────
def test_accumulation_entry():
    cands = [_target()] + _filler()
    orders = decide_accumulation(_view({}), cands, {'T001': 900})
    b = [o for o in _buys(orders) if o['code'] == 'T001']
    assert len(b) == 1 and '매집' in b[0]['reason']


def test_accumulation_entry_takes_half_weight():
    """2단 피라미딩 — 매집 단계는 목표 비중(15%)의 절반만 산다."""
    cands = [_target()] + _filler()
    orders = decide_accumulation(_view({}), cands, {'T001': 900})
    b = [o for o in _buys(orders) if o['code'] == 'T001'][0]
    # 1단은 최종 비중의 절반이다(2단으로 나눠 채운다).
    assert b['quantity'] == int(3_000_000 * POSITION_WEIGHT / 2 / 900)


def test_no_entry_when_crowd_already_arrived():
    """군중축이 양(+)이면 이미 심리가 터진 것 — Sim1의 영역이지 심8이 아니다."""
    cands = [_target(unique_posters=9999)] + _filler()
    orders = decide_accumulation(_view({}), cands, {'T001': 900})
    assert [o for o in _buys(orders) if o['code'] == 'T001'] == []


def test_no_entry_below_anchor_zone():
    # 52주 고점의 60% — 앵커 구간 밖
    cands = [_target(w52_hgpr=1500)] + _filler()
    orders = decide_accumulation(_view({}), cands, {'T001': 900})
    assert [o for o in _buys(orders) if o['code'] == 'T001'] == []


def test_no_entry_without_52w_data():
    cands = [_target(w52_hgpr=0, w52_lwpr=0)] + _filler()
    orders = decide_accumulation(_view({}), cands, {'T001': 900})
    assert [o for o in _buys(orders) if o['code'] == 'T001'] == []


def test_no_entry_when_illiquid():
    cands = [_target(amount=500_000_000)] + _filler()
    orders = decide_accumulation(_view({}), cands, {'T001': 900})
    assert [o for o in _buys(orders) if o['code'] == 'T001'] == []


def test_no_signal_when_sample_too_thin():
    """표본이 얇으면 z를 만들지 않는다 — 후보 3개 중 1등이 이상신호로 둔갑하는 것을 막는다."""
    cands = [_target()] + _filler(3)
    orders = decide_accumulation(_view({}), cands, {'T001': 900})
    assert _buys(orders) == []


def test_breakout_entry_at_new_high():
    # 신고가(=52주 고점) + 정보축 양 + 거래대금 z 양
    cands = [_target(price=1000, amount=50_000_000_000)] + _filler()
    orders = decide_accumulation(_view({}), cands, {'T001': 1000})
    b = [o for o in _buys(orders) if o['code'] == 'T001']
    assert len(b) == 1 and '돌파' in b[0]['reason']


def test_pyramiding_fills_remaining_weight():
    """매집으로 절반 채운 종목이 돌파하면 남은 절반을 채운다."""
    held = {'T001': {'name': '매집주', 'quantity': 250, 'avg_price': 900, 'peak_price': 900}}
    cands = [_target(price=1000, amount=50_000_000_000)] + _filler()
    orders = decide_accumulation(_view(held), cands, {'T001': 1000})
    b = [o for o in _buys(orders) if o['code'] == 'T001']
    assert len(b) == 1 and '추가매수' in b[0]['reason']
    assert b[0]['quantity'] == int((3_000_000 * POSITION_WEIGHT - 250 * 900) / 1000)


def test_no_pyramiding_when_weight_already_full():
    held = {'T001': {'name': '매집주', 'quantity': 450, 'avg_price': 1000, 'peak_price': 1000}}
    cands = [_target(price=1000, amount=50_000_000_000)] + _filler()
    orders = decide_accumulation(_view(held), cands, {'T001': 1000})
    assert [o for o in _buys(orders) if o['code'] == 'T001'] == []


# ── 청산 ────────────────────────────────────────────────
def test_exit_on_info_reversal():
    """정보거래자가 사라지면 나온다 — 이 전략의 근거가 사라진 것이다."""
    held = {'T001': {'name': '매집주', 'quantity': 10, 'avg_price': 900, 'peak_price': 900}}
    cands = [_target(frgn_fake_ntby_qty=-5_000_000, orgn_fake_ntby_qty=-3_000_000,
                     foreign_change=-5.0)] + _filler()
    orders = decide_accumulation(_view(held), cands, {'T001': 900})
    s = _sells(orders)
    assert len(s) == 1 and '정보축 반전' in s[0]['reason']


def test_exit_on_anchor_break():
    held = {'T001': {'name': '매집주', 'quantity': 10, 'avg_price': 900, 'peak_price': 900}}
    cands = [_target(price=880, w52_hgpr=1500)] + _filler()
    orders = decide_accumulation(_view(held), cands, {'T001': 880})
    s = _sells(orders)
    assert len(s) == 1 and '앵커 이탈' in s[0]['reason']


def test_trailing_stop_after_gain():
    held = {'T001': {'name': '매집주', 'quantity': 10, 'avg_price': 900, 'peak_price': 1000}}
    orders = decide_accumulation(_view(held), _filler(), {'T001': 960})
    s = _sells(orders)
    assert len(s) == 1 and '트레일링' in s[0]['reason']


def test_hard_stop():
    held = {'T001': {'name': '매집주', 'quantity': 10, 'avg_price': 1000, 'peak_price': 1000}}
    orders = decide_accumulation(_view(held), _filler(), {'T001': 940})
    s = _sells(orders)
    assert len(s) == 1 and '손절' in s[0]['reason']


def test_holding_absent_from_candidates_is_not_touched():
    """오늘 후보에 없으면 정보축을 계산할 수 없다 — 없는 근거로 팔지 않는다."""
    held = {'ZZZ': {'name': '이탈주', 'quantity': 10, 'avg_price': 1000, 'peak_price': 1000}}
    orders = decide_accumulation(_view(held), _filler(), {'ZZZ': 1000})
    assert _sells(orders) == []
