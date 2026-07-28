import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from datetime import datetime, timedelta
from src.strategy.simulators.sim9_gap_fade import decide_gap_fade

NOW_LATE = datetime(2026, 7, 28, 15, 3)     # 스크래퍼 오후 런 (진입 가능 시각)
NOW_EARLY = datetime(2026, 7, 28, 11, 0)    # 되밀림 미확정 시각
NOW_AUCTION = datetime(2026, 7, 28, 15, 33)  # 동시호가 이후 = 체결 불가


def _view(portfolio, nav=3_000_000):
    return {'portfolio': portfolio, 'cash': nav, 'initial_cash': 3_000_000, 'nav': nav,
            'cooldown_codes': {}, 'market_index_healthy': True}


def _pos(avg, entry_dt, qty=10):
    return {'name': 'T', 'quantity': qty, 'avg_price': avg, 'peak_price': avg,
            'entry_date': entry_dt.strftime('%Y-%m-%d')}


def _cand(price=1000, open_px=1100, prev_close=1000, amount=2_000_000_000,
          day_high=1120, day_low=990):
    """기본값 = 갭 +10%, 장중 -9.1%, 일중위치 0.08 (진입 조건 충족)"""
    return [{'code': '222', 'name': '갭주', 'price': price, 'open_price': open_px,
             'prev_close': prev_close, 'amount': amount,
             'day_high': day_high, 'day_low': day_low}]


# ── 진입 ────────────────────────────────────────────────
def test_entry_on_gap_up_and_intraday_fade():
    orders = decide_gap_fade(_view({}), _cand(), {'222': 1000}, now=NOW_LATE)
    buys = [o for o in orders if o['action'] == 'BUY']
    assert len(buys) == 1 and buys[0]['code'] == '222'


def test_no_entry_before_1430():
    """되밀림 확정 전 진입 금지 — 시각 게이트가 이 전략의 핵심."""
    orders = decide_gap_fade(_view({}), _cand(), {'222': 1000}, now=NOW_EARLY)
    assert [o for o in orders if o['action'] == 'BUY'] == []


def test_no_entry_after_auction_starts():
    """15:20 이후엔 이 가격으로 체결할 수 없다. 백테스트가 거짓이 되는 지점."""
    orders = decide_gap_fade(_view({}), _cand(), {'222': 1000}, now=NOW_AUCTION)
    assert [o for o in orders if o['action'] == 'BUY'] == []


def test_no_entry_when_gap_too_small():
    # 갭 +4.0% (<7.0), 되밀림·일중위치는 충족
    orders = decide_gap_fade(_view({}), _cand(price=950, open_px=1040), {'222': 950}, now=NOW_LATE)
    assert [o for o in orders if o['action'] == 'BUY'] == []


def test_no_entry_when_fade_too_shallow():
    # 갭 +10%, 장중 -2.7% (>-6.0) — 되밀림 깊이가 주신호다
    orders = decide_gap_fade(_view({}), _cand(price=1070, open_px=1100, day_high=1120,
                                              day_low=1060), {'222': 1070}, now=NOW_LATE)
    assert [o for o in orders if o['action'] == 'BUY'] == []


def test_no_entry_when_not_near_day_low():
    """일중위치 0.5 — 되밀림이 중간에 걸친 종목. 실측 전 구간 최악(-11.5%)."""
    orders = decide_gap_fade(_view({}), _cand(day_high=1010, day_low=990),
                             {'222': 1000}, now=NOW_LATE)
    assert [o for o in orders if o['action'] == 'BUY'] == []


def test_no_entry_without_day_range():
    """고가/저가가 없으면 일중 위치를 판단할 수 없다 — 없는 근거로 사지 않는다."""
    orders = decide_gap_fade(_view({}), _cand(day_high=0, day_low=0),
                             {'222': 1000}, now=NOW_LATE)
    assert [o for o in orders if o['action'] == 'BUY'] == []


def test_no_entry_when_illiquid():
    orders = decide_gap_fade(_view({}), _cand(amount=500_000_000), {'222': 1000}, now=NOW_LATE)
    assert [o for o in orders if o['action'] == 'BUY'] == []


def test_no_entry_without_open_price():
    """시가가 없으면 갭을 만들어내지 않고 건너뛴다."""
    orders = decide_gap_fade(_view({}), _cand(open_px=0), {'222': 1000}, now=NOW_LATE)
    assert [o for o in orders if o['action'] == 'BUY'] == []


# ── 청산 ────────────────────────────────────────────────
def test_hold_on_entry_day_even_when_down():
    """진입 당일 오버나이트 보유가 전략의 본체 — 당일엔 손절도 하지 않는다."""
    pos = {'222': _pos(1000, NOW_LATE)}
    orders = decide_gap_fade(_view(pos), [], {'222': 940}, now=NOW_LATE)
    assert [o for o in orders if o['action'] == 'SELL'] == []


def test_no_fixed_take_profit():
    """고정 익절 없음 — +3% 익절이 알파를 파괴한다는 실측(n=136)에 따른 규칙."""
    entry = NOW_LATE - timedelta(days=1)
    pos = {'222': _pos(1000, entry)}
    orders = decide_gap_fade(_view(pos), [], {'222': 1080}, now=datetime(2026, 7, 28, 10, 0))
    assert [o for o in orders if o['action'] == 'SELL'] == []


def test_next_day_stop_loss():
    entry = NOW_LATE - timedelta(days=1)
    pos = {'222': _pos(1000, entry)}
    orders = decide_gap_fade(_view(pos), [], {'222': 970}, now=datetime(2026, 7, 28, 10, 0))
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '손절' in sells[0]['reason']


def test_next_day_holds_until_close():
    """익일 장중 무익무손이면 종가까지 들고 간다."""
    entry = NOW_LATE - timedelta(days=1)
    pos = {'222': _pos(1000, entry)}
    orders = decide_gap_fade(_view(pos), [], {'222': 1005}, now=datetime(2026, 7, 28, 10, 0))
    assert [o for o in orders if o['action'] == 'SELL'] == []


def test_next_day_time_stop_at_close():
    entry = NOW_LATE - timedelta(days=1)
    pos = {'222': _pos(1000, entry)}
    orders = decide_gap_fade(_view(pos), [], {'222': 1005}, now=NOW_LATE)
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '타임스탑' in sells[0]['reason']


def test_stale_position_sold_regardless_of_time():
    """휴장 등으로 청산을 놓친 2일 이상 포지션은 시각 불문 청산."""
    entry = NOW_LATE - timedelta(days=3)
    pos = {'222': _pos(1000, entry)}
    orders = decide_gap_fade(_view(pos), [], {'222': 1005}, now=datetime(2026, 7, 28, 10, 0))
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '타임스탑' in sells[0]['reason']


def test_unknown_entry_date_sold_immediately():
    pos = {'222': {'name': 'T', 'quantity': 10, 'avg_price': 1000, 'peak_price': 1000}}
    orders = decide_gap_fade(_view(pos), [], {'222': 1005}, now=datetime(2026, 7, 28, 10, 0))
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '진입일 불명' in sells[0]['reason']
