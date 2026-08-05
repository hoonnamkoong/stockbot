"""[2026-08-05] Sim4·Sim4-1 진입에 ADX 상한(60) 추가.

배경: 심4+4-1 합산 26건 실거래 재집계에서 ADX 60을 기점으로 승률·평균ROI가
뒤집혔다(설계문서 docs/superpowers/specs/2026-08-05-sim4-sim4-1-performance-improvements.md).
과열(추세가 이미 다 나온) 종목 진입을 거르는 상한이 실제로 걸리는지 검증한다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators.sim4_bull_daytrading import decide_bull_daytrade, ADX_MAX as ADX_MAX_41
from src.strategy.simulators.sim4_bull_momentum import BullMomentumSimulator

NAV = 3_000_000

# ADX(Efficiency Ratio 근사) = |direction| / sum(|변동폭|) * 100.
# 완만한 등락(direction 대비 변동폭이 큼) → 중간값. 단조 상승 → 100(과열).
MID_ADX_SPARKLINE = [90, 95, 90, 98, 93, 100]     # direction 10, volatility 26 → ADX≈38.5
HOT_ADX_SPARKLINE = [90, 94, 98, 102, 106, 110]   # 단조 상승 → ADX=100


def _view(portfolio=None, cash=NAV, nav=NAV):
    return {'portfolio': portfolio or {}, 'cash': cash, 'initial_cash': NAV, 'nav': nav,
            'cooldown_codes': {}}


def _cand(code, sparkline, price=1000):
    return {'code': code, 'name': f'종목{code}', 'price': price, 'amount': 5_000_000_000,
            'sparkline_price': sparkline, 'change_rate': '+3.0%',
            'orgn_fake_ntby_qty': 100, 'frgn_fake_ntby_qty': 0, 'tick_power': 130.0}


def test_sim4_1_rejects_overheated_adx():
    """[Sim4-1] ADX>=60(과열)이면 다른 조건이 다 맞아도 진입하지 않는다."""
    orders = decide_bull_daytrade(_view(), [_cand('111', HOT_ADX_SPARKLINE)], {'111': 1000})
    assert not any(o['action'] == 'BUY' for o in orders)


def test_sim4_1_still_enters_on_mid_adx():
    """[Sim4-1] ADX가 상한 아래(20~60)면 기존과 동일하게 진입한다 — 회귀 방지."""
    orders = decide_bull_daytrade(_view(), [_cand('111', MID_ADX_SPARKLINE)], {'111': 1000})
    buys = [o for o in orders if o['action'] == 'BUY']
    assert len(buys) == 1 and buys[0]['code'] == '111'


def _sim4(tmp_path):
    s = BullMomentumSimulator(initial_cash=NAV)
    s.state_file = str(tmp_path / "s.json")
    s.csv_file = str(tmp_path / "s.csv")
    s.log_file = str(tmp_path / "s.log")
    s.state = {'initial_cash': NAV, 'cash': NAV, 'invested': 0, 'portfolio': {},
               'peak_nav': NAV, 'total_fees': 0, 'history': [NAV], 'daily_trades': [],
               'cooldown_codes': {}}
    return s


def test_sim4_rejects_overheated_adx(tmp_path):
    """[Sim4] ADX>=60(과열)이면 다른 조건이 다 맞아도 진입하지 않는다."""
    sim = _sim4(tmp_path)
    sim.run([_cand('111', HOT_ADX_SPARKLINE)], {'111': 1000})
    assert '111' not in sim.state['portfolio']


def test_sim4_still_enters_on_mid_adx(tmp_path):
    """[Sim4] ADX가 상한 아래(20~60)면 기존과 동일하게 진입한다 — 회귀 방지."""
    sim = _sim4(tmp_path)
    sim.run([_cand('111', MID_ADX_SPARKLINE)], {'111': 1000})
    assert '111' in sim.state['portfolio']


def test_thresholds_match_between_sim4_and_sim4_1():
    """두 심의 ADX 상한이 서로 어긋나지 않는지 — 재집계는 둘을 합산해서 냈으므로
    한쪽만 바뀌면 그 합산 표본의 전제가 깨진다."""
    assert BullMomentumSimulator.ADX_MAX == ADX_MAX_41
