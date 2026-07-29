"""Sim6의 국면 게이팅 — 읽기 실패를 '국면 아님'으로 오해하면 실제 매도가 나간다.

Sim6는 tradeable이라 비 BEAR 청산 경로가 실전에서 진짜 시장가 매도다.
그런데 _read_regime이 파일 없음·파싱 실패·알 수 없는 값을 전부 'SIDEWAYS'로
뭉개면, 일시적 파일 오류가 곧바로 포지션 청산이 된다. '국면이 아니다'와
'판단할 수 없다'는 다르다 — 후자에선 아무것도 하지 않고 다음 사이클을 기다린다.
"""
import json
import os
import sys
import tempfile

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators.sim6_bear_hedge import BearHedgeSimulator

_MANIFEST = os.path.join(os.path.dirname(__file__), '..', 'src', 'strategy', 'strategy_manifest.yaml')


def _sim(tmpdir, regime=None, portfolio=None):
    """격리 인스턴스. data_dir까지 tmpdir로 돌려 실제 data/를 안 건드린다."""
    sim = BearHedgeSimulator(initial_cash=3_000_000)
    sim.data_dir = tmpdir
    sim.state_file = os.path.join(tmpdir, 'sim_bear_state.json')
    sim.log_file = os.path.join(tmpdir, 'sim_bear_log.json')
    sim.csv_file = os.path.join(tmpdir, 'trade_history_sim_bear.csv')
    sim.reset_state()
    if regime is not None:
        with open(os.path.join(tmpdir, 'sim_libero_state.json'), 'w', encoding='utf-8') as f:
            json.dump({'current_regime': regime}, f)
    if portfolio:
        sim.state['portfolio'] = portfolio
        sim.state['cash'] = 100_000
    return sim


def _held():
    return {'114800': {'name': 'KODEX 인버스', 'quantity': 100, 'avg_price': 6000,
                       'peak_price': 6000, 'entry_date': '2026-07-28', 'is_scaled_out': False}}


# ── 읽기 실패는 청산 사유가 아니다 ──────────────────────────────
def test_missing_libero_state_does_not_liquidate():
    """파일이 없으면 판단 불가다. 보유분을 팔면 안 된다."""
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, regime=None, portfolio=_held())
        sim.run([], current_prices={'114800': 6000})
        assert '114800' in sim.state['portfolio']
        assert sim.state['portfolio']['114800']['quantity'] == 100


def test_corrupt_libero_state_does_not_liquidate():
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, regime=None, portfolio=_held())
        with open(os.path.join(d, 'sim_libero_state.json'), 'w', encoding='utf-8') as f:
            f.write('{깨진 JSON')
        sim.run([], current_prices={'114800': 6000})
        assert sim.state['portfolio']['114800']['quantity'] == 100


def test_unknown_regime_value_does_not_liquidate():
    """알 수 없는 값도 '판단 불가'다 — 조용히 SIDEWAYS로 간주하면 매도가 나간다."""
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, regime='BANANA', portfolio=_held())
        sim.run([], current_prices={'114800': 6000})
        assert sim.state['portfolio']['114800']['quantity'] == 100


def test_read_regime_returns_none_when_undeterminable():
    with tempfile.TemporaryDirectory() as d:
        assert _sim(d)._read_regime() is None
        assert _sim(d, regime='BANANA')._read_regime() is None


# ── 확인된 비 BEAR는 여전히 청산한다 ───────────────────────────
def test_confirmed_non_bear_liquidates():
    """국면을 실제로 읽어 BEAR가 아님을 확인했으면 청산은 그대로 일어나야 한다."""
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, regime='SIDEWAYS', portfolio=_held())
        sim.run([], current_prices={'114800': 6000})
        assert '114800' not in sim.state['portfolio']


@pytest.mark.parametrize('regime', ['BULL', 'SIDEWAYS'])
def test_all_confirmed_non_bear_regimes_liquidate(regime):
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, regime=regime, portfolio=_held())
        sim.run([], current_prices={'114800': 6000})
        assert '114800' not in sim.state['portfolio']


def test_bear_reads_through():
    with tempfile.TemporaryDirectory() as d:
        assert _sim(d, regime='BEAR')._read_regime() == 'BEAR'


# ── 국면 생산자가 소비자보다 먼저 돌아야 한다 ───────────────────
def test_libero_runs_before_its_consumers():
    """Sim0가 뒤에 있으면 Sim6·Sim10은 항상 직전 사이클의 국면으로 판단한다.

    get_active_simulators가 매니페스트 순서를 그대로 보존하고, 그 순서가
    trade_engine의 실행 순서다(소비자 1곳). 국면이 뒤집히는 사이클에서
    한 박자 늦는 것을 막는다.
    """
    with open(_MANIFEST, encoding='utf-8') as f:
        ids = [s['id'] for s in yaml.safe_load(f)['simulators']]
    producer = ids.index('sim0_libero')
    for consumer in ('sim6_bear', 'sim10_orchestrator'):
        assert producer < ids.index(consumer), \
            f"sim0_libero가 {consumer}보다 뒤에 있다 — 국면이 한 사이클 낡는다"
