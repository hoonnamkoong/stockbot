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


def test_injected_metrics_drive_bull_regime(tmp_path):
    sim = _libero(tmp_path)
    sim.live_market_metrics = {'breadth': 70, 'momentum': 3.0, 'trend': 30, 'sample': 100}
    # 국면 확정은 스무딩(5회 과반)이라 instant_regime로 검증
    candidates = [{'code': '1', 'change_rate': '+1.0%', 'sparkline_price': [100, 101, 102]}]
    sim.run(candidates)
    assert sim.state['instant_regime'] == 'BULL'
    assert sim.state['breadth_source'] == 'top100_live'


def test_injected_weak_metrics_trigger_bear(tmp_path):
    sim = _libero(tmp_path)
    # 진짜 하락장: breadth 낮고 momentum 음수, trend 존재 → 버즈풀이었으면 못 잡던 BEAR
    sim.live_market_metrics = {'breadth': 30, 'momentum': -3.0, 'trend': 20, 'sample': 100}
    candidates = [{'code': '1', 'change_rate': '+2.0%', 'sparkline_price': [100, 90, 80]}]
    sim.run(candidates)
    assert sim.state['instant_regime'] == 'BEAR'


def test_no_injection_falls_back_to_buzz(tmp_path):
    sim = _libero(tmp_path)
    # live_market_metrics 미설정 → 후보 기반 폴백, breadth_source='candidates'
    candidates = [{'code': '1', 'change_rate': '+1.0%', 'sparkline_price': [100, 101, 102]}]
    sim.run(candidates)
    assert sim.state['breadth_source'] == 'candidates'
