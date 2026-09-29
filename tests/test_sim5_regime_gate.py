"""심5 국면 게이트 — 신규 진입은 약한횡보·하락·매우하락에서만, 청산은 항상.

설계서 §9(09-29 사용자 확정). 게이트는 심6처럼 run()에 있다 — 페이퍼
(trade_engine._run_simulators)와 실전(program_trader)이 같은 run()을 부르므로
두 경로가 같은 파일(data_dir/sim_libero_state.json의 regime6)을 같은 방식으로 읽는다.

regime6가 None(파일 없음·깨짐·모르는 값)이면 진입하지 않는다(fail-closed).
심6와 달리 청산은 계속한다 — 심5의 청산(손절·RSI2·타임스탑)은 국면을 보지 않는
규칙이라 '판단 불가'가 손절을 막으면 안 된다.
"""
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators.sim5_sideways_swing import SidewaysSwingSimulator, entry_allowed

BOX = [1100, 1200, 1150, 1200, 1100, 1180, 1050, 1160, 1100, 1200,
       1150, 1190, 1100, 1160, 1080, 1060, 1040, 1025, 1010, 1000]


def _sim(tmpdir, regime6=None, portfolio=None, raw=None):
    sim = SidewaysSwingSimulator(initial_cash=3_000_000)
    sim.data_dir = tmpdir
    sim.state_file = os.path.join(tmpdir, 'sim_sideways_state.json')
    sim.log_file = os.path.join(tmpdir, 'sim_sideways_log.json')
    sim.csv_file = os.path.join(tmpdir, 'trade_history_sim_sideways.csv')
    sim.reset_state()
    path = os.path.join(tmpdir, 'sim_libero_state.json')
    if raw is not None:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(raw)
    elif regime6 is not None:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'current_regime': 'SIDEWAYS', 'regime6': regime6}, f)
    if portfolio:
        sim.state['portfolio'] = portfolio
        sim.state['cash'] = 3_000_000 - sum(p['avg_price'] * p['quantity']
                                            for p in portfolio.values())
        sim.state['invested'] = 3_000_000 - sim.state['cash']
    return sim


def _cand():
    return [{'code': '222', 'name': '레인지', 'price': 1000, 'amount': 2_000_000_000,
             'range_history': list(BOX), 'change_rate': '+0.5%'}]


def _held():
    return {'005930': {'name': '삼성', 'quantity': 10, 'avg_price': 1000,
                       'peak_price': 1000, 'entry_date': '2026-09-28',
                       'is_scaled_out': False}}


@pytest.mark.parametrize('r6', ['WEAK_SIDEWAYS', 'BEAR', 'STRONG_BEAR'])
def test_entry_in_allowed_regimes(r6):
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, regime6=r6)
        sim.run(_cand(), current_prices={'222': 1000})
        assert '222' in sim.state['portfolio']


@pytest.mark.parametrize('r6', ['STRONG_SIDEWAYS', 'BULL', 'STRONG_BULL'])
def test_no_entry_in_blocked_regimes(r6):
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, regime6=r6)
        sim.run(_cand(), current_prices={'222': 1000})
        assert sim.state['portfolio'] == {}


@pytest.mark.parametrize('setup', ['missing', 'corrupt', 'unknown'])
def test_no_entry_when_regime6_undeterminable(setup):
    with tempfile.TemporaryDirectory() as d:
        if setup == 'missing':
            sim = _sim(d)
        elif setup == 'corrupt':
            sim = _sim(d, raw='{깨진 JSON')
        else:
            sim = _sim(d, regime6='BANANA')
        sim.run(_cand(), current_prices={'222': 1000})
        assert sim.state['portfolio'] == {}


@pytest.mark.parametrize('r6', ['STRONG_SIDEWAYS', 'BULL', None])
def test_stop_loss_still_fires_when_entry_blocked(r6):
    """차단 국면·판단 불가에서도 청산은 돈다(−5% 손절)."""
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, regime6=r6, portfolio=_held())
        sim.run([], current_prices={'005930': 950})
        assert '005930' not in sim.state['portfolio']


def test_entry_allowed_helper():
    assert entry_allowed('WEAK_SIDEWAYS') and entry_allowed('BEAR') and entry_allowed('STRONG_BEAR')
    for r in ('STRONG_SIDEWAYS', 'BULL', 'STRONG_BULL', None, 'SIDEWAYS', ''):
        assert not entry_allowed(r)
