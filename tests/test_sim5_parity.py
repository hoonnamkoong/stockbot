import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from datetime import date
from src.strategy.simulators.sim5_sideways_swing import decide_sideways


def _view(portfolio, cash=3_000_000, healthy=True):
    return {'portfolio': portfolio, 'cash': cash, 'initial_cash': 3_000_000,
            'cooldown_codes': {}, 'market_index_healthy': healthy}


def _pos(avg, qty=10):
    return {'name': 'T', 'quantity': qty, 'avg_price': avg, 'peak_price': avg,
            'entry_date': date.today().isoformat()}


def test_take_profit_plus_4pct():
    orders = decide_sideways(_view({'005930': _pos(1000)}), [], {'005930': 1040})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '익절' in sells[0]['reason']


def test_hard_stop_minus_3pct():
    orders = decide_sideways(_view({'005930': _pos(1000)}), [], {'005930': 970})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '손절' in sells[0]['reason']


def test_pullback_entry():
    # 추세(ADX≥20) + 우상향 + MA5 이하 눌림 1~10% + 당일 -2%초과 + tick
    cand = [{'code': '222', 'name': '눌림주', 'price': 104, 'amount': 2_000_000_000,
             'sparkline_price': [100, 108, 110, 112, 106], 'change_rate': '-1.0%', 'tick_power': 110.0}]
    orders = decide_sideways(_view({}), cand, {'222': 104})
    buys = [o for o in orders if o['action'] == 'BUY']
    assert len(buys) == 1 and buys[0]['code'] == '222'
