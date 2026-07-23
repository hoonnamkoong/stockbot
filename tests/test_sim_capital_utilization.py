"""[자본 활용률] 심의 사이징이 예수금을 구조적으로 놀리지 않는지 검증.

배경(2026-07-23): 라이브 실측에서 Sim3 5.7% / Sim5 5.0% / Sim4 63.3% / Sim7 47.9%로
투입률이 낮았고, 원인은 전략 신호가 아니라 사이징 구조였다.
  A. MAX_HOLDINGS × 종목당 비중이 100%에 한참 못 미침 (Sim3 30%, Sim4 62.5%, Sim5 40%)
  B. Sim7만 분모가 '잔여 현금'이라 매수마다 복리로 감쇠 (5번째 픽 = 첫 픽의 60%)
  C. 분모가 initial_cash 고정이라 수익금이 영구 유휴 현금으로 남음
여기서 A/B/C의 재발을 각각 잠근다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from src.strategy.simulators import (
    sim3_risk,
    sim4_bull_daytrading,
    sim4_bull_momentum,
    sim5_sideways_swing,
    sim6_bear_hedge,
    sim7_report_follower,
)
from src.strategy.simulators.sim4_bull_daytrading import decide_bull_daytrade
from src.strategy.simulators.sim5_sideways_swing import SidewaysSwingSimulator, decide_sideways

NAV = 3_000_000


def _sim(tmp_path, cls=SidewaysSwingSimulator, cash=NAV, portfolio=None):
    s = cls(initial_cash=NAV)
    s.state_file = str(tmp_path / "s.json")
    s.csv_file = str(tmp_path / "s.csv")
    s.log_file = str(tmp_path / "s.log")
    s.state = {'initial_cash': NAV, 'cash': cash, 'invested': 0, 'portfolio': portfolio or {},
               'peak_nav': NAV, 'total_fees': 0, 'history': [NAV], 'daily_trades': [],
               'market_index_healthy': True, 'cooldown_codes': {}}
    return s


def _view(portfolio=None, cash=NAV, nav=NAV, healthy=True):
    return {'portfolio': portfolio or {}, 'cash': cash, 'initial_cash': NAV, 'nav': nav,
            'cooldown_codes': {}, 'market_index_healthy': healthy}


# ---------------------------------------------------------------- 원인 A: 상한
# (종목당 비중 × 최대 보유수)가 90% 수준이어야 한다. 미달이면 남은 예수금은 영원히 못 쓴다.
CAPS = [
    ("Sim3 가치페어", sim3_risk.SmartRiskSimulator.POSITION_WEIGHT, sim3_risk.SmartRiskSimulator.MAX_HOLDINGS),
    ("Sim4 상승모멘텀", sim4_bull_momentum.BullMomentumSimulator.POSITION_WEIGHT,
     sim4_bull_momentum.BullMomentumSimulator.MAX_HOLDINGS),
    ("Sim4-1 단타", sim4_bull_daytrading.POSITION_WEIGHT, sim4_bull_daytrading.MAX_HOLDINGS),
    ("Sim5 레인지", sim5_sideways_swing.POSITION_WEIGHT, sim5_sideways_swing.MAX_HOLDINGS),
    ("Sim6 인버스", sim6_bear_hedge.ENTRY_RATIO, sim6_bear_hedge.MAX_HOLDINGS),
    ("Sim7 리포트", sim7_report_follower.ReportFollowerSimulator.WEIGHT_MAX,
     sim7_report_follower.ReportFollowerSimulator.MAX_HOLDINGS),
]


@pytest.mark.parametrize("label,weight,max_holdings", CAPS)
def test_max_deployment_reaches_90pct(label, weight, max_holdings):
    """상한이 90% 미만이면 그만큼 예수금이 구조적으로 잠긴다."""
    assert weight * max_holdings == pytest.approx(0.90, abs=0.01), \
        f"{label}: 최대 투입률 {weight * max_holdings:.0%} (목표 90%)"


@pytest.mark.parametrize("label,weight,max_holdings", CAPS)
def test_max_deployment_not_over_100pct(label, weight, max_holdings):
    """반대로 100%를 넘으면 마지막 매수가 현금 부족으로 조용히 실패한다."""
    assert weight * max_holdings <= 1.0, f"{label}: 최대 투입률 {weight * max_holdings:.0%}"


# ---------------------------------------------------------------- 원인 C: NAV 분모
def test_calc_nav_counts_holdings_at_market_price(tmp_path):
    s = _sim(tmp_path, cash=1_000_000,
             portfolio={'005930': {'name': 'T', 'quantity': 10, 'avg_price': 100_000}})
    assert s.calc_nav({'005930': 120_000}) == 2_200_000


def test_calc_nav_falls_back_to_avg_price_when_quote_missing(tmp_path):
    """현재가 조회 실패를 0으로 처리하면 NAV가 꺼져 사이징이 쪼그라든다 → 취득원가로 폴백."""
    s = _sim(tmp_path, cash=1_000_000,
             portfolio={'005930': {'name': 'T', 'quantity': 10, 'avg_price': 100_000}})
    assert s.calc_nav({}) == 2_000_000


def test_view_exposes_nav(tmp_path):
    s = _sim(tmp_path, cash=1_000_000,
             portfolio={'005930': {'name': 'T', 'quantity': 10, 'avg_price': 100_000}})
    assert s._view({'005930': 120_000})['nav'] == 2_200_000


def test_sizing_grows_with_profit():
    """수익으로 NAV가 커지면 종목당 매수 금액도 같이 커져야 한다(수익금 재투자)."""
    base = decide_bull_daytrade(_view(nav=3_000_000), _momentum_candidates(1), {'C0': 1_000})
    grown = decide_bull_daytrade(_view(nav=6_000_000), _momentum_candidates(1), {'C0': 1_000})
    assert grown[0]['quantity'] == 2 * base[0]['quantity']


# ---------------------------------------------------------------- 실제 투입률
def _momentum_candidates(n):
    """Sim4-1/Sim4 진입 조건(기간모멘텀 5~40%, ADX>=20, 당일상승, 수급, 유동성)을 모두 만족."""
    return [{'code': f'C{i}', 'name': f'종목{i}', 'price': 1_000, 'amount': 5_000_000_000,
             'sparkline_price': [900, 950, 1000, 1050, 1100], 'change_rate': '+3.0%',
             'orgn_fake_ntby_qty': 100, 'frgn_fake_ntby_qty': 0, 'tick_power': 130.0}
            for i in range(n)]


def _range_candidates(n):
    """Sim5 진입 조건(채널폭>=8%, 저점 +3% 이내, 당일 급락 아님)을 모두 만족."""
    return [{'code': f'R{i}', 'name': f'레인지{i}', 'price': 1_020, 'amount': 5_000_000_000,
             'range_history': [1000, 1020, 1040, 1060, 1080, 1100, 1050, 1030, 1010, 1000],
             'change_rate': '+0.5%'}
            for i in range(n)]


def test_sim4_1_fills_to_90pct():
    cands = _momentum_candidates(10)
    orders = decide_bull_daytrade(_view(), cands, {c['code']: 1_000 for c in cands})
    buys = [o for o in orders if o['action'] == 'BUY']
    spent = sum(o['quantity'] * o['price'] for o in buys)
    assert len(buys) == sim4_bull_daytrading.MAX_HOLDINGS
    assert spent / NAV == pytest.approx(0.90, abs=0.01)


def test_sim5_fills_to_90pct():
    cands = _range_candidates(10)
    orders = decide_sideways(_view(), cands, {c['code']: 1_020 for c in cands})
    buys = [o for o in orders if o['action'] == 'BUY']
    spent = sum(o['quantity'] * o['price'] for o in buys)
    assert len(buys) == sim5_sideways_swing.MAX_HOLDINGS
    assert spent / NAV == pytest.approx(0.90, abs=0.01)


# ---------------------------------------------------------------- 원인 B: Sim7 복리 감쇠
def test_sim7_position_sizes_do_not_decay(tmp_path):
    """잔여현금 기준이면 뒤로 갈수록 매수액이 줄어든다. NAV 기준이면 균등해야 한다."""
    s = _sim(tmp_path, cls=sim7_report_follower.ReportFollowerSimulator)
    picks = [{'code': f'P{i}', 'name': f'픽{i}', 'current_price': 1_000} for i in range(6)]
    s.buy_from_report(picks, bull_score=100.0)  # weight = WEIGHT_MAX

    costs = [p['quantity'] * p['avg_price'] for p in s.state['portfolio'].values()]
    assert len(costs) == sim7_report_follower.ReportFollowerSimulator.MAX_HOLDINGS
    assert max(costs) - min(costs) <= 1_000, f"매수액 감쇠 발생: {costs}"
    assert sum(costs) / NAV == pytest.approx(0.90, abs=0.01)
