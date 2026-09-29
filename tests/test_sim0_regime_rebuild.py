import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest
from src.strategy.simulators.sim0_libero import LiberoSimulator


def _libero(tmp_path):
    sim = LiberoSimulator()
    sim.state_file = str(tmp_path / "libero_state.json")
    sim.log_file = str(tmp_path / "libero_log.json")
    sim.csv_file = str(tmp_path / "libero_trades.csv")
    sim.state = {'initial_cash': 0, 'cash': 0, 'invested': 0, 'portfolio': {},
                 'peak_nav': 0, 'total_fees': 0, 'history': [0], 'daily_trades': [],
                 'market_index_healthy': True, 'cooldown_codes': {}, 'regime_history': []}
    return sim


def test_bull_score_drops_foreign_and_reweights():
    sim = LiberoSimulator.__new__(LiberoSimulator)  # __init__ 없이 메서드만
    # breadth=100, momentum=0(→50), trend=100 → 100*0.4 + 50*0.35 + 100*0.25 = 82.5
    assert sim.calc_bull_score(100, 0, 100) == 82.5


def test_injected_metrics_drive_bull_score(tmp_path):
    # 2026-09-29부터 국면은 6단계 판정(regime6)이 정한다. 주입 실측은 bull_score만 움직인다.
    sim = _libero(tmp_path)
    sim.live_market_metrics = {'breadth': 70, 'momentum': 3.0, 'trend': 30, 'sample': 100}
    candidates = [{'code': '1', 'change_rate': '+1.0%', 'sparkline_price': [100, 101, 102]}]
    sim.run(candidates)
    # 70*0.4 + (50+3*5)*0.35 + 30*0.25 = 58.25
    assert sim.state['bull_score'] == pytest.approx(58.2, abs=0.1)
    assert sim.state['breadth_source'] == 'top100_live'


def test_injected_weak_metrics_drive_bull_score_down(tmp_path):
    sim = _libero(tmp_path)
    # 버즈 후보는 상승(+2%)이어도 top100 실측이 약하면 실측을 쓴다
    sim.live_market_metrics = {'breadth': 30, 'momentum': -3.0, 'trend': 20, 'sample': 100}
    candidates = [{'code': '1', 'change_rate': '+2.0%', 'sparkline_price': [100, 90, 80]}]
    sim.run(candidates)
    # 30*0.4 + (50-3*5)*0.35 + 20*0.25 = 29.25
    assert sim.state['bull_score'] == pytest.approx(29.2, abs=0.1)


def test_injected_metrics_with_none_trend_falls_back_to_buzz_adx(tmp_path):
    sim = _libero(tmp_path)
    # trend CSV 파싱 실패(None)라도 breadth/momentum은 라이브 실측을 그대로 써야 함
    # (trend를 breadth/momentum과 묶어서 통째로 버즈풀로 되돌리면 안 됨)
    sim.live_market_metrics = {'breadth': 65, 'momentum': 1.5, 'trend': None, 'sample': 100}
    candidates = [
        {'code': '1', 'change_rate': '+1.0%', 'sparkline_price': [100]},
        {'code': '2', 'change_rate': '+2.0%', 'sparkline_price': [100]},
    ]
    sim.run(candidates)
    assert sim.state['breadth_source'] == 'top100_live'
    assert sim.state['metrics']['breadth_score'] == 65.0
    assert sim.state['metrics']['momentum_score'] == 1.5
    # trend는 None이 아니라 버즈 후보 ADX median으로 폴백되어야 함 (크래시 금지)
    assert sim.state['metrics']['trend_strength'] == 0.0


def test_no_injection_falls_back_to_buzz(tmp_path):
    sim = _libero(tmp_path)
    # live_market_metrics 미설정 → 후보 기반 폴백, breadth_source='candidates'
    candidates = [{'code': '1', 'change_rate': '+1.0%', 'sparkline_price': [100, 101, 102]}]
    sim.run(candidates)
    assert sim.state['breadth_source'] == 'candidates'
