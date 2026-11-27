"""보유 종목 이력 공급 계약 — 가짜 provider만 쓴다(네트워크 없음)."""
import re
from pathlib import Path

import pytest

from src.trade import holding_history as hh
from src.trade.holding_history import (
    HISTORY_DAYS, MIN_CAND_HISTORY, attach_holding_history, supply_holding_history)


class FakeProvider:
    def __init__(self, data=None, raises=()):
        self.data = data or {}
        self.raises = set(raises)
        self.calls = []

    def get_daily_history(self, code, days=250):
        self.calls.append(code)
        if code in self.raises:
            raise RuntimeError('boom')
        return self.data.get(code, [])


def _rows(n=3):
    return [{'date': f'2026110{i + 1}', 'open': 1, 'high': 1, 'low': 1,
             'close': 100.0 + i, 'volume': 1, 'amount': 1} for i in range(n)]


def _long(n=MIN_CAND_HISTORY):
    return [{'date': f'{20260000 + i + 1}', 'close': 1.0} for i in range(n)]


def test_short_candidate_history_is_refetched():
    p = FakeProvider({'A': _rows()})
    cands = {'A': {'price_history': _long(2)}}
    out = supply_holding_history(['A'], cands, p, log=lambda *_: None)
    assert p.calls == ['A'] and 'A' in out


def test_skips_codes_already_in_candidates():
    p = FakeProvider({'A': _rows()})
    cands = {'A': {'code': 'A', 'price_history': _long()}}
    out = supply_holding_history(['A'], cands, p, log=lambda *_: None)
    assert p.calls == [] and out == {}


def test_fetches_only_the_rest():
    p = FakeProvider({'B': _rows(), 'C': _rows()})
    cands = {'A': {'price_history': _long()}}
    out = supply_holding_history({'A': {}, 'B': {}, 'C': {}}, cands, p, log=lambda *_: None)
    assert sorted(p.calls) == ['B', 'C']
    assert set(out) == {'B', 'C'}
    assert out['B'] == [{'date': r['date'], 'close': r['close']} for r in _rows()]


def test_failed_lookup_is_absent_not_empty():
    p = FakeProvider({'B': _rows()})  # 'X'는 []를 돌려준다
    out = supply_holding_history(['X', 'B'], {}, p, log=lambda *_: None)
    assert 'X' not in out and 'B' in out


def test_delisted_code_does_not_raise():
    p = FakeProvider({'B': _rows()}, raises=['X'])
    out = supply_holding_history(['X', 'B'], {}, p, log=lambda *_: None)
    assert set(out) == {'B'}


def test_etf_code_absence_is_logged():
    lines = []
    p = FakeProvider({'B': _rows()})
    supply_holding_history(['ETF', 'B'], {}, p, log=lines.append)
    assert len(lines) == 1 and '공급 1종목' in lines[0] and '실패 1' in lines[0]


def test_requests_history_days():
    seen = {}

    class P:
        def get_daily_history(self, code, days=250):
            seen['days'] = days
            return _rows()
    supply_holding_history(['A'], {}, P(), log=lambda *_: None)
    assert seen['days'] == HISTORY_DAYS == 25


def _sim(tmp_path=None):
    """__init__을 우회한다 — 정상 생성은 data/에 상태 파일을 만들어 복원 카운트를 부풀린다."""
    from src.strategy.simulators.base_simulator import BaseSimulator

    class S(BaseSimulator):
        def run(self, *a, **k):
            pass
    s = S.__new__(S)
    s.state = {'portfolio': {}, 'cash': 0}
    s.initial_cash = 1
    return s


def test_view_carries_price_history(tmp_path):
    s = _sim(tmp_path)
    s.price_history = {'A': [{'date': '20261101', 'close': 1.0}]}
    assert s._view()['price_history'] == s.price_history


def test_view_defaults_to_empty_dict(tmp_path):
    assert _sim(tmp_path)._view()['price_history'] == {}


def test_base_init_sets_empty_price_history(monkeypatch, tmp_path):
    from src.strategy.simulators import base_simulator as bs

    class S(bs.BaseSimulator):
        def run(self, *a, **k):
            pass
    monkeypatch.setattr(S, 'load_state', lambda self: None)
    monkeypatch.setattr(bs.os, 'makedirs', lambda *a, **k: None)
    assert S('x').price_history == {}


def test_both_paths_call_the_same_supplier():
    root = Path(__file__).resolve().parent.parent / 'src' / 'pipeline' / 'workers'
    for name in ('trade_engine.py', 'program_trader.py'):
        src = (root / name).read_text(encoding='utf-8')
        assert 'attach_holding_history(' in src
        assert 'get_daily_history' not in src  # 각자 구현한 루프 금지


def test_program_trader_supplies_after_adapter_before_run():
    src = (Path(__file__).resolve().parent.parent / 'src' / 'pipeline' / 'workers'
           / 'program_trader.py').read_text(encoding='utf-8')
    a = src.index('orders = _make_adapter(')
    b = src.index('attach_holding_history(', a)
    c = src.index('sim.run(sim_candidates', a)
    assert a < b < c


def _held_sim(portfolio):
    s = _sim()
    s.state['portfolio'] = portfolio
    return s


def test_attach_swallows_infrastructure_failure_and_sets_empty():
    sim = _held_sim({'A': {}})
    sim.price_history = {'stale': []}
    errs = []

    def boom():
        raise RuntimeError('auth down')
    attach_holding_history(sim, [], boom, log=lambda *_: None, log_error=errs.append)
    assert sim.price_history == {}
    assert 'RuntimeError' in errs[0]


@pytest.mark.parametrize('exc', [TypeError, AttributeError, KeyError])
def test_attach_reraises_programming_errors(exc):
    sim = _held_sim({'A': {}})

    def boom():
        raise exc('bug')
    with pytest.raises(exc):
        attach_holding_history(sim, [], boom, log=lambda *_: None, log_error=lambda *_: None)


def test_attach_empty_portfolio_never_builds_provider():
    sim = _held_sim({})
    sim.price_history = {'stale': []}

    def must_not():
        raise AssertionError('공급자를 만들면 안 된다')
    attach_holding_history(sim, [], must_not, log=lambda *_: None, log_error=lambda *_: None)
    assert sim.price_history == {}


def test_engine_with_holdings_never_builds_real_kis_provider(monkeypatch):
    """보유가 있는 심이 픽스처에 들어와도 실제 KIS 공급자(인증·네트워크)는 생성되지 않는다."""
    from src.pipeline.workers import trade_engine
    from src.trade import kis_data_provider

    def real_ctor(*a, **k):
        raise AssertionError('실제 KISDataProvider 생성 금지')
    monkeypatch.setattr(kis_data_provider.KISDataProvider, '__init__', real_ctor)
    fake = FakeProvider({'A': _rows()})
    monkeypatch.setattr(hh, 'make_kis_provider', lambda: fake)

    class Sim:
        IS_ANALYZER = False
        IS_EOD = False

        def __init__(self):
            self.state = {'portfolio': {'A': {'quantity': 1, 'avg_price': 100}}}
            self.seen = None

        def get_universe(self):
            return []

        def run(self, candidates, current_prices=None):
            self.seen = dict(self.price_history)

    sim = Sim()
    monkeypatch.setattr('src.strategy.registry.get_simulator_by_id', lambda *a, **k: sim)
    w = trade_engine.TradeEngineWorker.__new__(trade_engine.TradeEngineWorker)
    w.log = lambda *a, **k: None
    w.log_error = lambda *a, **k: None
    w._enrich_universe = lambda stocks: stocks
    w._run_simulators([], only_sim_id='x', allow_price_fallback=True,
                      universe_override=[{'code': 'Z', 'price': 1}])
    assert fake.calls == ['A'] and 'A' in (sim.seen or {})
