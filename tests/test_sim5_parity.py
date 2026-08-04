import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from datetime import date
from src.strategy.simulators.sim5_sideways_swing import decide_sideways


def _view(portfolio, cash=3_000_000, nav=3_000_000):
    return {'portfolio': portfolio, 'cash': cash, 'initial_cash': 3_000_000, 'nav': nav,
            'cooldown_codes': {}}


def _pos(avg, qty=10):
    return {'name': 'T', 'quantity': qty, 'avg_price': avg, 'peak_price': avg,
            'entry_date': date.today().isoformat()}


def _hist(low=1000, high=1200, n=10):
    """채널 산출용 종가 이력. MIN_HISTORY(10) 이상이어야 채널이 만들어진다."""
    return [low] * n + [high]


def test_no_fixed_take_profit():
    """고정 익절은 2026-07-21 재설계로 폐지됐다.

    구 '추세 눌림목(+4% 고정익절)'은 목표가가 종목 실제 변동폭과 무관해
    이겨봐야 수수료였다. 지금은 상단 돌파 시 승자를 계속 라이딩한다.
    """
    orders = decide_sideways(_view({'005930': _pos(1000)}), [], {'005930': 1040})
    assert [o for o in orders if o['action'] == 'SELL'] == []


def test_trailing_exit_after_peak_nears_channel_top():
    """트레일링은 고점이 채널 상단에 근접했을 때만 발동한다(상단 스윙/돌파)."""
    pos = _pos(1000)
    pos['peak_price'] = 1190          # 채널 상단 1200의 98%(=1176) 초과 → 발동
    cand = [{'code': '005930', 'name': 'T', 'range_history': _hist()}]
    orders = decide_sideways(_view({'005930': pos}), cand, {'005930': 1160})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '트레일링' in sells[0]['reason']


def test_no_trailing_before_peak_nears_channel_top():
    """상단 근처에 못 간 포지션은 -2% 되밀림만으로 털지 않는다."""
    pos = _pos(1000)
    pos['peak_price'] = 1050          # 상단 근접(1176) 미달
    cand = [{'code': '005930', 'name': 'T', 'range_history': _hist()}]
    orders = decide_sideways(_view({'005930': pos}), cand, {'005930': 1020})
    assert [o for o in orders if o['action'] == 'SELL'] == []


def test_hard_stop_minus_3pct():
    orders = decide_sideways(_view({'005930': _pos(1000)}), [], {'005930': 970})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '손절' in sells[0]['reason']


def _range_stock(price, **over):
    s = {'code': '222', 'name': '레인지주', 'price': price, 'amount': 2_000_000_000,
         'range_history': _hist(), 'change_rate': '-1.0%'}
    s.update(over)
    return s


def test_channel_low_entry():
    """진입은 채널 저점 +3% 이내에서만. MA5 눌림 진입은 폐지됐다."""
    cand = [_range_stock(1020)]        # 저점 1000의 +2%
    orders = decide_sideways(_view({}), cand, {'222': 1020})
    buys = [o for o in orders if o['action'] == 'BUY']
    assert len(buys) == 1 and buys[0]['code'] == '222'


def test_no_entry_above_low_zone():
    cand = [_range_stock(1100)]        # 저점 +10% — 구간 밖
    assert [o for o in decide_sideways(_view({}), cand, {'222': 1100})
            if o['action'] == 'BUY'] == []


def test_no_entry_when_channel_too_narrow():
    """채널 폭이 좁으면 수수료 대비 무의미한 셋업이라 건너뛴다."""
    cand = [_range_stock(1005, range_history=_hist(high=1050))]   # 폭 5% < 8%
    assert [o for o in decide_sideways(_view({}), cand, {'222': 1005})
            if o['action'] == 'BUY'] == []


def test_no_entry_on_sharp_daily_drop():
    """저점 근처라도 당일 -2% 초과 급락이면 떨어지는 칼이다."""
    cand = [_range_stock(1020, change_rate='-5.0%')]
    assert [o for o in decide_sideways(_view({}), cand, {'222': 1020})
            if o['action'] == 'BUY'] == []
