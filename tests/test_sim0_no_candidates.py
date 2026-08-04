"""E2 (2026-08-04 스크래퍼 지연 재설계): Sim0가 candidates 없이도 국면을 판정한다.

breadth/momentum/trend는 top100 라이브 실측(live_market_metrics)에서 오고,
candidates(버즈 후보)는 foreign·volatility(둘 다 표시 전용, calc_bull_score
미사용)에만 쓰인다. 그런데 run()의 `if not candidates:` 조기 반환이 라이브
실측이 있어도 국면 갱신을 막고 있었다.

이 게이트가 매매를 앞으로 옮기는 순서 가변화(E3)의 전제조건이다 — Sim10의
라우팅이 Sim0의 국면을 읽으므로, 스크래핑 전에 매매를 내려면 스크래핑 전에
국면도 갱신돼야 한다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators.sim0_libero import LiberoSimulator


def _sim(tmp_path):
    s = LiberoSimulator()
    s.state_file = str(tmp_path / "libero.json")
    s.csv_file = str(tmp_path / "libero.csv")
    s.log_file = str(tmp_path / "libero.log")
    s.state = {'last_run': None, 'current_regime': None}
    return s


def test_regime_updates_from_live_metrics_without_candidates(tmp_path):
    """candidates=[]라도 live_market_metrics가 있으면 국면을 계산해야 한다."""
    s = _sim(tmp_path)
    s.live_market_metrics = {'breadth': 83.0, 'momentum': 3.5, 'trend': 45.0, 'sample': 100}
    result = s.run([], current_prices={})
    assert result['current_regime'] in ('BULL', 'SIDEWAYS', 'BEAR')
    assert result['metrics']['breadth_score'] == 83.0
    assert result['breadth_source'] == 'top100_live'


def test_bull_regime_reachable_without_candidates(tmp_path):
    """국면 산출식 자체가 candidates 없이도 BULL까지 도달할 수 있어야 한다."""
    s = _sim(tmp_path)
    s.live_market_metrics = {'breadth': 90.0, 'momentum': 5.0, 'trend': 80.0, 'sample': 100}
    result = s.run([], current_prices={})
    assert result['instant_regime'] == 'BULL'


def test_no_candidates_and_no_metrics_keeps_previous_regime(tmp_path):
    """candidates도 없고 라이브 실측도 없으면 — 여전히 판단 불가, 직전 국면 유지."""
    s = _sim(tmp_path)
    s.state['current_regime'] = 'BULL'
    s.live_market_metrics = None
    result = s.run([], current_prices={})
    assert result['current_regime'] == 'BULL'  # 갱신되지 않고 그대로


def test_foreign_and_volatility_are_none_without_candidates(tmp_path):
    """foreign·volatility는 후보 종목에서만 나온다 — 없으면 0.0으로 지어내지 않고 None."""
    s = _sim(tmp_path)
    s.live_market_metrics = {'breadth': 70.0, 'momentum': 1.0, 'trend': 30.0, 'sample': 100}
    result = s.run([], current_prices={})
    assert result['metrics']['foreign_score'] is None
    assert result['metrics']['volatility_score'] is None


def test_candidates_present_behavior_unchanged(tmp_path):
    """candidates가 있는 기존 경로는 그대로 — foreign·volatility가 실제로 계산된다."""
    s = _sim(tmp_path)
    s.live_market_metrics = None
    candidates = [
        {'change_rate': '+2.00%', 'sparkline_price': [100, 102, 104], 'foreign_change': 1.5},
        {'change_rate': '-1.00%', 'sparkline_price': [100, 99, 98], 'foreign_change': -0.5},
    ]
    result = s.run(candidates, current_prices={})
    assert result['breadth_source'] == 'candidates'
    assert result['metrics']['foreign_score'] == 0.5
    assert result['metrics']['volatility_score'] is not None
