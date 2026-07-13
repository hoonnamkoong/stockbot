import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from datetime import date
from src.strategy.simulators.sim4_bull_daytrading import decide_bull_daytrade


def _view(portfolio, cash=3_000_000, healthy=True):
    return {'portfolio': portfolio, 'cash': cash, 'initial_cash': 3_000_000,
            'cooldown_codes': {}, 'market_index_healthy': healthy}


def _pos(avg, qty=10, partial=False, entry=None):
    return {'name': 'T', 'quantity': qty, 'avg_price': avg, 'peak_price': avg,
            'entry_date': entry or date.today().isoformat(), 'partial_sold': partial}


def test_stop_loss_minus_3pct():
    orders = decide_bull_daytrade(_view({'005930': _pos(1000)}), [], {'005930': 960})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and sells[0]['quantity'] is None and '손절' in sells[0]['reason']


def test_partial_take_profit_at_plus_5pct():
    orders = decide_bull_daytrade(_view({'005930': _pos(1000)}), [], {'005930': 1050})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and sells[0]['quantity'] == 5 and sells[0]['mark_partial'] is True


def test_breakeven_stop_after_partial():
    orders = decide_bull_daytrade(_view({'005930': _pos(1000, partial=True)}), [], {'005930': 1000})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '매입가 복귀' in sells[0]['reason']


def test_entry_when_conditions_met():
    cand = [{'code': '111', 'name': '진입주', 'price': 1000, 'amount': 5_000_000_000,
             'sparkline_price': [90, 95, 100, 105, 110], 'change_rate': '+3.0%',
             'orgn_fake_ntby_qty': 100, 'frgn_fake_ntby_qty': 0, 'tick_power': 130.0}]
    orders = decide_bull_daytrade(_view({}), cand, {'111': 1000})
    buys = [o for o in orders if o['action'] == 'BUY']
    assert len(buys) == 1 and buys[0]['code'] == '111'
