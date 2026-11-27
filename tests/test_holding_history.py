"""보유 종목 이력 공급 계약 — 가짜 provider만 쓴다(네트워크 없음)."""
import re
from pathlib import Path

from src.trade.holding_history import HISTORY_DAYS, supply_holding_history


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


def test_skips_codes_already_in_candidates():
    p = FakeProvider({'A': _rows()})
    cands = {'A': {'code': 'A', 'price_history': [{'date': '20261101', 'close': 1.0}]}}
    out = supply_holding_history(['A'], cands, p, log=lambda *_: None)
    assert p.calls == [] and out == {}


def test_fetches_only_the_rest():
    p = FakeProvider({'B': _rows(), 'C': _rows()})
    cands = {'A': {'price_history': [{'date': '20261101', 'close': 1.0}]}}
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


def _sim(tmp_path):
    from src.strategy.simulators.base_simulator import BaseSimulator

    class S(BaseSimulator):
        def run(self, *a, **k):
            pass
    s = S('hh_test')
    s.data_dir = str(tmp_path)
    return s


def test_view_carries_price_history(tmp_path):
    s = _sim(tmp_path)
    s.price_history = {'A': [{'date': '20261101', 'close': 1.0}]}
    assert s._view()['price_history'] == s.price_history


def test_view_defaults_to_empty_dict(tmp_path):
    assert _sim(tmp_path)._view()['price_history'] == {}


def test_both_paths_call_the_same_supplier():
    root = Path(__file__).resolve().parent.parent / 'src' / 'pipeline' / 'workers'
    for name in ('trade_engine.py', 'program_trader.py'):
        src = (root / name).read_text(encoding='utf-8')
        assert 'supply_holding_history(' in src
        assert 'get_daily_history' not in src  # 각자 구현한 루프 금지


def test_program_trader_supplies_after_adapter_before_run():
    src = (Path(__file__).resolve().parent.parent / 'src' / 'pipeline' / 'workers'
           / 'program_trader.py').read_text(encoding='utf-8')
    a = src.index('orders = _make_adapter(')
    b = src.index('supply_holding_history(', a)
    c = src.index('sim.run(sim_candidates', a)
    assert a < b < c
