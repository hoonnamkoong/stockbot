"""Sim10의 국면 게이팅 — 지어낸 국면으로 전략을 실행하지 않는다.

Sim10은 국면에 따라 하위 전략을 갈아탄다(BULL=단타, SIDEWAYS=눌림목, BEAR=인버스).
_read_regime이 파일 없음·파싱 실패·알 수 없는 값을 'SIDEWAYS'로 뭉개면 두 가지가
동시에 깨진다.
  1. 근거 없는 SIDEWAYS로 눌림목 전략이 실제로 돌아 신규 진입까지 낼 수 있다.
  2. 그 값이 state["active_regime"]에 박히는데, program_trader._resolve_active_tag가
     이걸 실거래 턴의 손익 귀속 태그로 읽는다 — 없는 국면에 손익이 붙는다.

Sim6와 증상은 다르지만(그쪽은 청산) 뿌리는 같다: 판단 불가는 판단이 아니다.
"""
import json
import os
import sys
import tempfile
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators import sim10_orchestrator
from src.strategy.simulators.sim10_orchestrator import Sim10OrchestratorSimulator


def _sim(tmpdir, regime=None, prior_regime='BEAR'):
    sim = Sim10OrchestratorSimulator(initial_cash=3_000_000)
    sim.data_dir = tmpdir
    sim.state_file = os.path.join(tmpdir, 'sim_orchestrator_state.json')
    sim.log_file = os.path.join(tmpdir, 'sim_orchestrator_log.json')
    sim.csv_file = os.path.join(tmpdir, 'trade_history_sim_orchestrator.csv')
    sim.reset_state()
    sim.state['active_regime'] = prior_regime
    if regime is not None:
        with open(os.path.join(tmpdir, 'sim_libero_state.json'), 'w', encoding='utf-8') as f:
            json.dump({'current_regime': regime, 'bull_score': 71.5}, f)
    return sim


def _run_watching_strategies(sim):
    """하위 전략 3개를 감시하며 run(). 어느 것도 불리면 안 되는 경우를 잡는다."""
    with mock.patch.object(sim10_orchestrator, 'decide_bull_daytrade', return_value=[]) as bull, \
         mock.patch.object(sim10_orchestrator, 'decide_sideways', return_value=[]) as side, \
         mock.patch.object(sim10_orchestrator, 'decide_sim6', return_value=[]) as bear:
        sim.run([], current_prices={})
    return bull, side, bear


# ── 판단 불가면 어떤 하위 전략도 돌지 않는다 ────────────────────
@pytest.mark.parametrize('setup', ['missing', 'corrupt', 'unknown'])
def test_no_strategy_runs_when_regime_undeterminable(setup):
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, regime='BANANA' if setup == 'unknown' else None)
        if setup == 'corrupt':
            with open(os.path.join(d, 'sim_libero_state.json'), 'w', encoding='utf-8') as f:
                f.write('{깨진 JSON')
        bull, side, bear = _run_watching_strategies(sim)
        assert not bull.called and not side.called and not bear.called


def test_active_regime_not_overwritten_when_undeterminable():
    """실거래 턴 회계가 이 값을 손익 귀속 태그로 읽는다 — 지어낸 값을 박으면 안 된다."""
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, regime=None, prior_regime='BEAR')
        _run_watching_strategies(sim)
        assert sim.state['active_regime'] == 'BEAR'


def test_read_regime_returns_none_when_undeterminable():
    with tempfile.TemporaryDirectory() as d:
        assert _sim(d)._read_regime()[0] is None
        assert _sim(d, regime='BANANA')._read_regime()[0] is None


# ── 확인된 국면은 그대로 동작한다 ──────────────────────────────
@pytest.mark.parametrize('regime,called_idx', [('BULL', 0), ('SIDEWAYS', 1), ('BEAR', 2)])
def test_confirmed_regime_runs_its_strategy(regime, called_idx):
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, regime=regime)
        called = _run_watching_strategies(sim)
        assert called[called_idx].called
        assert sim.state['active_regime'] == regime


def test_confirmed_regime_keeps_bull_score():
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, regime='BULL')
        _run_watching_strategies(sim)
        assert sim.state['active_bull_score'] == 71.5


# ── SIDEWAYS 위임에도 심5의 6단계 게이트(전일 확정값)를 건다 ─────────
# 10-01 사용자 결정: 심10이 3단계로 SIDEWAYS에 라우팅해도 전일 확정 6단계가
# 강한횡보면 심5 신규 진입 없음. 청산(−5% 손절)은 항상. 심5·Sim14와 같은
# regime_state.read_regime6_confirmed를 읽는다(장중 regime6가 아니다).
_BOX = [1100, 1200, 1150, 1200, 1100, 1180, 1050, 1160, 1100, 1200,
        1150, 1190, 1100, 1160, 1080, 1060, 1040, 1025, 1010, 1000]
_BASE6 = {'WEAK_SIDEWAYS': {'level': 0, 'vol10': 0.5},
          'STRONG_SIDEWAYS': {'level': 0, 'vol10': 1.5}}


def _sideways_sim(tmpdir, base6, intraday=None):
    sim = _sim(tmpdir)
    payload = {'current_regime': 'SIDEWAYS', 'bull_score': 50.0, 'regime6': intraday}
    if base6 is not None:
        payload['regime6_state'] = {'base': _BASE6[base6], 'today': None}
    with open(os.path.join(tmpdir, 'sim_libero_state.json'), 'w', encoding='utf-8') as f:
        json.dump(payload, f)
    return sim


def _box_cand():
    return [{'code': '222', 'name': '레인지', 'price': 1000, 'amount': 2_000_000_000,
             'range_history': list(_BOX), 'change_rate': '+0.5%'}]


@pytest.mark.parametrize('base6,intraday,expect_buy', [
    ('WEAK_SIDEWAYS', 'STRONG_SIDEWAYS', True),    # 전일 기준 — 장중 값은 안 본다
    ('STRONG_SIDEWAYS', 'WEAK_SIDEWAYS', False),
    ('STRONG_SIDEWAYS', None, False),
    (None, 'WEAK_SIDEWAYS', False),                # base 없음 → 판정 불가 → 진입 금지
])
def test_sideways_delegate_obeys_prev_confirmed_regime6(base6, intraday, expect_buy):
    with tempfile.TemporaryDirectory() as d:
        sim = _sideways_sim(d, base6, intraday)
        sim.run(_box_cand(), current_prices={'222': 1000})
        assert sim.state['active_regime'] == 'SIDEWAYS'
        assert ('222' in sim.state['portfolio']) is expect_buy


@pytest.mark.parametrize('base6', ['WEAK_SIDEWAYS', 'STRONG_SIDEWAYS', None])
def test_sideways_delegate_stop_loss_always_fires(base6):
    with tempfile.TemporaryDirectory() as d:
        sim = _sideways_sim(d, base6)
        sim.state['portfolio'] = {'005930': {'name': '삼성', 'quantity': 10, 'avg_price': 1000,
                                             'peak_price': 1000, 'entry_date': '2026-09-28',
                                             'is_scaled_out': False}}
        sim.state['cash'] = 3_000_000 - 10_000
        sim.state['invested'] = 10_000
        sim.run([], current_prices={'005930': 950})
        assert '005930' not in sim.state['portfolio']


def test_sideways_delegate_passes_gate_value():
    """allow_entry가 True 하드코딩이 아니라 게이트 값으로 넘어가는지 직접 본다."""
    with tempfile.TemporaryDirectory() as d:
        sim = _sideways_sim(d, 'STRONG_SIDEWAYS')
        _, side, _ = _run_watching_strategies(sim)
        assert side.call_args.kwargs['allow_entry'] is False
    with tempfile.TemporaryDirectory() as d:
        sim = _sideways_sim(d, 'WEAK_SIDEWAYS')
        _, side, _ = _run_watching_strategies(sim)
        assert side.call_args.kwargs['allow_entry'] is True
