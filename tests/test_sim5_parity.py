"""심5(레인지 저점 + RSI2 과매도) 판단 함수 규칙.

정본: docs/superpowers/specs/2026-09-29-sim5-regime-optimization.md §7·§8·§9.
decide_sideways는 순수 함수라 페이퍼(trade_engine._run_simulators)와 실전
(program_trader → 같은 심 객체의 run())이 같은 코드를 탄다. 국면 게이트는
run()에 있고(test_sim5_regime_gate.py), 여기서는 allow_entry 인자로만 본다.
"""
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators import sim5_sideways_swing as s5
from src.strategy.simulators.sim5_sideways_swing import decide_sideways, rsi2


def _view(portfolio, cash=3_000_000, nav=3_000_000):
    return {'portfolio': portfolio, 'cash': cash, 'initial_cash': 3_000_000, 'nav': nav,
            'cooldown_codes': {}}


def _pos(avg, qty=10, days_ago=0, peak=None):
    return {'name': 'T', 'quantity': qty, 'avg_price': avg,
            'peak_price': avg if peak is None else peak,
            'entry_date': (date.today() - timedelta(days=days_ago)).isoformat()}


# 박스 20일: 저점 1000 / 고점 1200(폭 20%). 끝으로 갈수록 내려와 과매도.
# ⚠ RSI2는 마지막 한 걸음에 매우 민감하다 — 현재가를 마지막 종가(1000)보다 +5만
# 올려도 RSI2가 28이 돼 진입이 막힌다. 그래서 기본 현재가는 마지막 종가와 같다.
BOX = [1100, 1200, 1150, 1200, 1100, 1180, 1050, 1160, 1100, 1200,
       1150, 1190, 1100, 1160, 1080, 1060, 1040, 1025, 1010, 1000]


def _box_to(x):
    """저점 1000(앞쪽)을 품고, 끝이 x로 흘러내리는 20일 박스 — 현재가 x에서 과매도."""
    body = [1100, 1200, 1150, 1200, 1000, 1180, 1050, 1160, 1100, 1200,
            1150, 1190, 1100, 1160, 1150]
    return body + [x + 80, x + 60, x + 40, x + 20, x]


def _stock(code='222', price=1000, **over):
    s = {'code': code, 'name': f'레인지{code}', 'price': price, 'amount': 2_000_000_000,
         'range_history': list(BOX), 'change_rate': '+0.5%'}
    s.update(over)
    return s


def _buys(orders):
    return [o for o in orders if o['action'] == 'BUY']


def _sells(orders):
    return [o for o in orders if o['action'] == 'SELL']


# ── 상수(§7) ─────────────────────────────────────────────────────────
def test_constants_match_spec():
    assert s5.MAX_HOLDINGS == 5 and s5.POSITION_WEIGHT == 0.19
    assert s5.MIN_HISTORY == 20
    assert s5.MIN_WIDTH_PCT == 8.0 and s5.LOW_ZONE == 0.03
    assert s5.DAILY_CRASH_PCT == -2.0 and s5.MIN_AMOUNT == 1_000_000_000
    assert s5.ENTRY_RSI2_MAX == 15.0 and s5.EXIT_RSI2_MIN == 70.0
    assert s5.STOP_PCT == -5.0 and s5.TIMEOUT_DAYS == 10
    assert not hasattr(s5, 'TRAIL_ARM_RATIO') and not hasattr(s5, 'TRAIL_CALLBACK_PCT')
    assert s5.ALLOWED_REGIMES6 == frozenset({'BEAR', 'STRONG_BEAR'})  # 10-02 G2


# ── RSI2 정의(§7 · §8) ───────────────────────────────────────────────
def test_rsi2_known_values():
    assert rsi2([1, 2]) == 100.0            # 하락 없음 = 100
    assert rsi2([2, 1]) == 0.0
    assert rsi2([1, 2, 1]) == pytest.approx(50.0)
    assert rsi2([1, 1, 1]) == 100.0         # 하락분 평균 0 → 100(연구 구현의 50과 다름, 설계 §7)


def test_rsi2_matches_research_harness_ewm():
    """연구 하네스 r3_lib.rsi2 = pandas ewm(alpha=0.5, adjust=False)와 같은 값."""
    pd = pytest.importorskip('pandas')
    closes = [100, 103, 101, 98, 99, 104, 102, 97, 95, 96, 99, 101, 100, 94, 92, 93,
              95, 90, 89, 91, 88]
    s = pd.Series(closes).diff()
    up = s.clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    dn = (-s.clip(upper=0)).ewm(alpha=0.5, adjust=False).mean()
    expected = float((100 - 100 / (1 + up / dn)).iloc[-1])
    assert rsi2(closes) == pytest.approx(expected, abs=1e-6)


def test_rsi2_undefined_for_short_input():
    assert rsi2([100]) is None and rsi2([]) is None


# ── 진입(§8-3) ───────────────────────────────────────────────────────
def test_entry_near_low_and_oversold():
    orders = decide_sideways(_view({}), [_stock()], {'222': 1000}, allow_entry=True)
    b = _buys(orders)
    assert len(b) == 1 and b[0]['quantity'] == int(3_000_000 * 0.19 / 1000)
    assert 'RSI2' in b[0]['reason']


def test_no_entry_when_gate_closed():
    funnel = []
    orders = decide_sideways(_view({}), [_stock()], {'222': 1000},
                             funnel=funnel, allow_entry=False)
    assert _buys(orders) == []
    assert [f['reason'] for f in funnel] == ['regime_gate']


@pytest.mark.parametrize('r,bought', [(14.99, True), (15.0, False), (40.0, False)])
def test_entry_rsi2_boundary(monkeypatch, r, bought):
    monkeypatch.setattr(s5, 'rsi2', lambda closes: r)
    funnel = []
    orders = decide_sideways(_view({}), [_stock()], {'222': 1000}, funnel=funnel,
                             allow_entry=True)
    assert bool(_buys(orders)) is bought
    if not bought:
        assert funnel[-1]['reason'] == 'rsi2_not_oversold'


def test_min_history_is_20():
    funnel = []
    short = _stock(range_history=BOX[1:])          # 19일
    assert _buys(decide_sideways(_view({}), [short], {'222': 1000}, funnel=funnel,
                                 allow_entry=True)) == []
    assert funnel[-1]['reason'] == 'no_channel'
    assert _buys(decide_sideways(_view({}), [_stock()], {'222': 1000},
                                 allow_entry=True))


def test_no_entry_above_low_zone():
    funnel = []
    cand = [_stock(price=1040)]                    # 저점 1000의 +4%
    assert _buys(decide_sideways(_view({}), cand, {'222': 1040}, funnel=funnel,
                                 allow_entry=True)) == []
    assert funnel[-1]['reason'] == 'not_near_low'


def test_no_entry_when_channel_too_narrow():
    funnel = []
    narrow = [1050, 1060, 1070, 1060, 1050, 1040, 1030, 1020, 1010, 1000] * 2   # 폭 7%
    cand = [_stock(range_history=narrow)]
    assert _buys(decide_sideways(_view({}), cand, {'222': 1000}, funnel=funnel,
                                 allow_entry=True)) == []
    assert funnel[-1]['reason'] == 'narrow_channel'


@pytest.mark.parametrize('chg,bought', [('-2.0%', False), ('-5.0%', False), ('-1.9%', True)])
def test_daily_crash_boundary(chg, bought):
    orders = decide_sideways(_view({}), [_stock(change_rate=chg)], {'222': 1000},
                             allow_entry=True)
    assert bool(_buys(orders)) is bought


def test_entry_fills_in_price_to_low_order():
    """후보 순서가 아니라 price/low 오름차순(동률은 코드순)으로 채운다(§1·§8)."""
    held = {f'H{i}': _pos(1000) for i in range(s5.MAX_HOLDINGS - 1)}   # 빈 자리 1개
    far = _stock(code='111', price=1025, range_history=_box_to(1025))   # 저점 대비 +2.5%
    near = _stock(code='333', price=1002, range_history=_box_to(1002))  # +0.2%
    # 두 후보 모두 조건을 통과해야 '정렬 때문에' 하나만 샀다는 뜻이 된다.
    assert len(_buys(decide_sideways(_view({}), [far, near], {'111': 1025, '333': 1002},
                                     allow_entry=True))) == 2
    prices = {'111': 1025, '333': 1002, **{c: 1000 for c in held}}
    orders = decide_sideways(_view(held), [far, near], prices, allow_entry=True)
    assert [o['code'] for o in _buys(orders)] == ['333']


def test_entry_tie_breaks_by_code():
    held = {f'H{i}': _pos(1000) for i in range(s5.MAX_HOLDINGS - 1)}
    prices = {'999': 1000, '100': 1000, **{c: 1000 for c in held}}
    orders = decide_sideways(_view(held), [_stock(code='999'), _stock(code='100')],
                             prices, allow_entry=True)
    assert [o['code'] for o in _buys(orders)] == ['100']


def test_missing_amount_field_is_logged_not_zero():
    funnel = []
    s = _stock(); del s['amount']
    decide_sideways(_view({}), [s], {'222': 1000}, funnel=funnel, allow_entry=True)
    assert funnel[-1]['reason'] == 'no_amount_field'


# ── 청산(§8-1): 국면과 무관 ─────────────────────────────────────────
@pytest.mark.parametrize('gate', [True, False])
def test_hard_stop_minus_5pct(gate):
    o = decide_sideways(_view({'005930': _pos(1000)}), [], {'005930': 950},
                        allow_entry=gate)
    assert len(_sells(o)) == 1 and '손절' in _sells(o)[0]['reason']
    assert _sells(o)[0]['cooldown'] == 3


def test_no_stop_at_minus_4_9pct():
    o = decide_sideways(_view({'005930': _pos(1000)}), [], {'005930': 951},
                        allow_entry=True)
    assert _sells(o) == []


@pytest.mark.parametrize('r,sold', [(70.0, False), (70.01, True)])
def test_exit_rsi2_boundary(monkeypatch, r, sold):
    monkeypatch.setattr(s5, 'rsi2', lambda closes: r)
    cand = [_stock(code='005930', price=1010)]
    o = decide_sideways(_view({'005930': _pos(1000)}), cand, {'005930': 1010},
                        allow_entry=False)
    assert bool(_sells(o)) is sold
    if sold:
        assert 'RSI2' in _sells(o)[0]['reason'] and _sells(o)[0]['cooldown'] == 2


def test_exit_rsi2_skipped_without_history(monkeypatch):
    """후보 밖(이력 없음)이면 RSI2 청산은 판정 불가 — 청산 조건 미충족과 섞지 않고 건너뛴다."""
    monkeypatch.setattr(s5, 'rsi2', lambda closes: 99.0)
    o = decide_sideways(_view({'005930': _pos(1000)}), [], {'005930': 1010},
                        allow_entry=True)
    assert _sells(o) == []


@pytest.mark.parametrize('days,sold', [(9, False), (10, True)])
def test_time_stop_10_calendar_days(monkeypatch, days, sold):
    monkeypatch.setattr(s5, 'rsi2', lambda closes: 50.0)
    cand = [_stock(code='005930', price=1010)]
    o = decide_sideways(_view({'005930': _pos(1000, days_ago=days)}), cand,
                        {'005930': 1010}, allow_entry=False)
    assert bool(_sells(o)) is sold
    if sold:
        assert '타임' in _sells(o)[0]['reason'] and _sells(o)[0]['cooldown'] == 1


def test_no_trailing_exit_anymore(monkeypatch):
    """채널 상단 트레일링은 폐지됐다 — 고점이 상단을 찍고 3% 되밀려도 팔지 않는다."""
    monkeypatch.setattr(s5, 'rsi2', lambda closes: 50.0)
    cand = [_stock(code='005930', price=1160)]
    o = decide_sideways(_view({'005930': _pos(1000, peak=1200)}), cand,
                        {'005930': 1160}, allow_entry=True)
    assert _sells(o) == []


def test_no_fixed_take_profit(monkeypatch):
    monkeypatch.setattr(s5, 'rsi2', lambda closes: 50.0)
    cand = [_stock(code='005930', price=1150)]
    o = decide_sideways(_view({'005930': _pos(1000)}), cand, {'005930': 1150},
                        allow_entry=True)
    assert _sells(o) == []


def test_sold_code_not_rebought_same_cycle():
    """손절한 종목이 같은 사이클에 저점 조건으로 다시 사지지 않는다."""
    cand = [_stock(code='005930', price=950,
                   range_history=[1100, 1200] * 9 + [960, 950])]
    o = decide_sideways(_view({'005930': _pos(1000)}), cand, {'005930': 950},
                        allow_entry=True)
    assert _buys(o) == [] and len(_sells(o)) == 1


def test_allow_entry_is_required():
    """호출자가 게이트를 잊으면 조용히 '진입 허용'이 되지 않게 필수 인자로 둔다."""
    with pytest.raises(TypeError):
        decide_sideways(_view({}), [_stock()], {'222': 1000})
