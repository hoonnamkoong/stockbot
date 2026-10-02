"""Sim10의 국면 게이팅 — 지어낸 국면으로 전략을 실행하지 않는다.

Sim10은 국면에 따라 하위 전략을 갈아탄다(BULL=단타, SIDEWAYS=눌림목, BEAR=현금 대기 —
10-01 결정으로 인버스 위임을 뺐다).
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
    """하위 전략을 감시하며 run(). 어느 것도 불리면 안 되는 경우를 잡는다.
    BEAR는 하위 전략 위임이 아니라 심10 자신의 현금 대기(decide_bear_cash)다(10-01)."""
    with mock.patch.object(sim10_orchestrator, 'decide_bull_daytrade', return_value=[]) as bull, \
         mock.patch.object(sim10_orchestrator, 'decide_sideways', return_value=[]) as side, \
         mock.patch.object(sim10_orchestrator, 'decide_bear_cash', return_value=[]) as bear:
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
          'STRONG_SIDEWAYS': {'level': 0, 'vol10': 1.5},
          'BEAR': {'level': -1, 'vol10': 1.0}}   # 전일 확정 하락 — 3단계는 오늘 SIDEWAYS로 바뀐 전환일


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
    ('BEAR', 'STRONG_SIDEWAYS', True),             # 전일 기준 — 장중 값은 안 본다
    ('WEAK_SIDEWAYS', 'BEAR', False),              # 10-02 G2: 약한횡보도 차단
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
        sim = _sideways_sim(d, 'BEAR')
        _, side, _ = _run_watching_strategies(sim)
        assert side.call_args.kwargs['allow_entry'] is True


# ── BEAR = 현금 대기 (10-01 결정) ───────────────────────────────────
# R6 연구: t−1 BEAR 조건부 다음 날 기댓값 ≈ 0, 인버스 위임(현행)이 BEAR 슬롯에서
# −43~−67%(복리 기여). 신규 BUY 없음, 보유분 전량 청산(가격 없으면 다음 사이클).
def _held(code, qty=10, avg=1000):
    return {code: {'name': code, 'quantity': qty, 'avg_price': avg, 'peak_price': avg,
                   'entry_date': '2026-09-28', 'is_scaled_out': False}}


def _bear_sim(tmpdir, portfolio):
    sim = _sim(tmpdir, regime='BEAR', prior_regime='SIDEWAYS')
    sim.state['portfolio'] = portfolio
    sim.state['invested'] = sum(p['quantity'] * p['avg_price'] for p in portfolio.values())
    sim.state['cash'] = 3_000_000 - sim.state['invested']
    return sim


def _perfect_inverse_cand():
    """구 심6 진입 조건을 완벽히 만족하는 인버스 — 그래도 사면 안 된다."""
    return [{'code': '114800', 'name': 'KODEX 인버스', 'price': 6000,
             'sparkline_price': [5000, 5200, 5500, 5800, 6000], 'change_rate': '+3.00%'}]


def test_bear_buys_nothing_even_with_perfect_inverse_candidate():
    with tempfile.TemporaryDirectory() as d:
        sim = _bear_sim(d, {})
        sim.run(_perfect_inverse_cand(), current_prices={'114800': 6000})
        assert sim.state['portfolio'] == {}
        assert sim.state['active_regime'] == 'BEAR'


def test_bear_sells_every_holding_including_inverse():
    with tempfile.TemporaryDirectory() as d:
        sim = _bear_sim(d, {**_held('005930'), **_held('114800', avg=6000)})
        sim.run([], current_prices={'005930': 1000, '114800': 6000})
        assert sim.state['portfolio'] == {}


def test_bear_does_not_sell_at_missing_price():
    with tempfile.TemporaryDirectory() as d:
        sim = _bear_sim(d, {**_held('005930'), **_held('000660')})
        sim.run([], current_prices={'005930': 1000})
        assert set(sim.state['portfolio']) == {'000660'}


def test_decide_bear_cash_is_sell_only():
    view = {'portfolio': {**_held('005930'), **_held('000660')}, 'cash': 0}
    orders = sim10_orchestrator.decide_bear_cash(view, {'005930': 1000, '000660': 0})
    assert [(o['action'], o['code'], o['quantity']) for o in orders] == [('SELL', '005930', None)]


def test_bear_universe_is_empty():
    """BEAR에서 인버스 유니버스를 주면 KIS 보강 호출만 는다 — 빈 목록."""
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, regime='BEAR')
        assert sim.get_universe() == []
        assert Sim10OrchestratorSimulator.needs_buzz('BEAR') is False


def test_sim10_no_longer_imports_sim6():
    src = open(sim10_orchestrator.__file__, encoding='utf-8').read()
    assert 'from .sim6_bear_hedge' not in src and 'decide_sim6(' not in src


def test_bear_paper_and_program_paths_produce_same_orders():
    """페이퍼(trade_engine → sim.run)와 실전(program_trader._make_adapter → sim.run)이
    같은 run()으로 같은 주문을 내는지 직접 호출로 본다."""
    from src.pipeline.workers.program_trader import _make_adapter
    pf = {**_held('005930'), **_held('114800', avg=6000), **_held('000660')}
    prices = {'005930': 1000, '114800': 6000}          # 000660은 가격 결손
    with tempfile.TemporaryDirectory() as d:
        paper = _bear_sim(d, {k: dict(v) for k, v in pf.items()})
        paper_orders = []
        paper._apply_orig = paper._apply
        paper._apply = lambda orders, cp=None: (paper_orders.extend(orders), paper._apply_orig(orders, cp))
        paper.run(_perfect_inverse_cand(), current_prices=dict(prices))
    with tempfile.TemporaryDirectory() as d:
        real = _bear_sim(d, {})
        snapshot = {'cash': 1_000_000, 'invested': 0, 'cooldown_codes': {},
                    'portfolio': {k: dict(v) for k, v in pf.items()},
                    'total_fees': 0, 'history': [3_000_000], 'daily_trades': [],
                    'peak_nav': 3_000_000, 'exec_path': 'program'}
        real_orders = _make_adapter(real, snapshot, '2026-10-01',
                                    real_holdings={k: {} for k in pf})
        real.run(_perfect_inverse_cand(), current_prices=dict(prices))
    assert sorted((o['action'].lower(), o['code']) for o in paper_orders) == \
        sorted((o['side'], o['code']) for o in real_orders) == \
        [('sell', '005930'), ('sell', '114800')]
