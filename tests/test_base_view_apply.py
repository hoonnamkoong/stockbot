import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.strategy.simulators.sim5_sideways_swing import SidewaysSwingSimulator
from src.strategy.simulators.base_simulator import get_kst_now


def _sim(tmp_path):
    s = SidewaysSwingSimulator(initial_cash=3_000_000)
    s.state_file = str(tmp_path / "s.json"); s.csv_file = str(tmp_path / "s.csv"); s.log_file = str(tmp_path / "s.log")
    s.state = {'initial_cash': 3_000_000, 'cash': 3_000_000, 'invested': 0, 'portfolio': {},
               'peak_nav': 3_000_000, 'total_fees': 0, 'history': [3_000_000], 'daily_trades': [],
               'cooldown_codes': {}}
    return s


def test_view_exposes_readonly_state(tmp_path):
    s = _sim(tmp_path)
    v = s._view()
    assert v['cash'] == 3_000_000 and v['initial_cash'] == 3_000_000
    assert v['portfolio'] == {}


def test_apply_buy_then_sell(tmp_path):
    s = _sim(tmp_path)
    s._apply([{'action': 'BUY', 'code': '005930', 'name': '삼성', 'price': 1000, 'quantity': 10,
               'reason': 'test', 'cooldown': None}], {'005930': 1000})
    assert '005930' in s.state['portfolio']
    s._apply([{'action': 'SELL', 'code': '005930', 'price': 1100, 'quantity': None,
               'reason': 'test', 'cooldown': 2, 'mark_partial': False}], {'005930': 1100})
    assert '005930' not in s.state['portfolio']
    assert '005930' in s.state['cooldown_codes']


def test_apply_partial_sell_sets_flag(tmp_path):
    s = _sim(tmp_path)
    s._apply([{'action': 'BUY', 'code': '005930', 'name': '삼성', 'price': 1000, 'quantity': 10,
               'reason': 'test', 'cooldown': None}], {'005930': 1000})
    s._apply([{'action': 'SELL', 'code': '005930', 'price': 1050, 'quantity': 5,
               'reason': 'partial', 'cooldown': None, 'mark_partial': True}], {'005930': 1050})
    assert s.state['portfolio']['005930']['partial_sold'] is True
    assert 'partial_sold_date' in s.state['portfolio']['005930']


def test_cooldown_active_staticmethod():
    from datetime import date, timedelta
    future = (date.today() + timedelta(days=2)).isoformat()
    past = (date.today() - timedelta(days=1)).isoformat()
    assert SidewaysSwingSimulator.cooldown_active({'A': future}, 'A') is True
    assert SidewaysSwingSimulator.cooldown_active({'A': past}, 'A') is False
    assert SidewaysSwingSimulator.cooldown_active({}, 'A') is False
