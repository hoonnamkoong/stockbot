import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from datetime import date
from src.strategy.simulators.sim4_bull_daytrading import decide_bull_daytrade


def _view(portfolio, cash=3_000_000, nav=3_000_000):
    return {'portfolio': portfolio, 'cash': cash, 'initial_cash': 3_000_000, 'nav': nav,
            'cooldown_codes': {}}


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
    """1차 분할익절을 찍은 종목이 본전으로 되돌아오면 남은 수량을 정리한다."""
    orders = decide_bull_daytrade(_view({'005930': _pos(1000, partial=True)}), [], {'005930': 985})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '매입가 복귀' in sells[0]['reason']


def test_breakeven_stop_fires_exactly_at_the_purchase_price():
    """정확히 본전(0%)에서 자른다 — 2026-09-16 원복.

    2026-08-20에 버퍼 -1.5%를 뒀다가 사후 측정으로 되돌렸다. 근거:

    **비용은 기계적이고 편익은 확률적이다.** BE손절이 걸리려면 가격이 0%를 반드시
    먼저 통과하므로 버퍼 폭만큼 **매번 확정적으로** 나쁜 가격에 나간다 —
    실측 8건 평균 **-1.60pp**. 반면 편익은 밴드에서 되돌아 나와야 하는 확률적
    사건인데, 밴드 진입 약 9건 중 **+10% 2차익절까지 회복 0건**, 어떤 형태로든
    플러스 청산은 1건(11%)으로 손익분기 필요확률 14.2%에 미달이다.
    순 -7.9pp / 19포지션.

    완화의 원래 관찰("며칠 더 버텼으면 더 나았다")은 완화 후에도 재현된다
    (페이퍼 T+1 71%, 평균 +6.8pp). 틀린 건 관찰이 아니라 **폭**이었다 —
    이 포지션들을 실제로 죽이는 되돌림 깊이는 -2~-4%대라 -1.5%는 비용만 내는
    자리였다. 그 패턴을 잡으려면 가격 완충이 아니라 시간 완충이어야 하고,
    그건 별도 설계다.
    """
    orders = decide_bull_daytrade(_view({'005930': _pos(1000, partial=True)}), [], {'005930': 1000})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '매입가 복귀' in sells[0]['reason']


def test_breakeven_stop_also_fires_inside_the_old_buffer_band():
    """옛 버퍼 구간(-1.5% ~ 0%)에서도 자른다 — 원복의 핵심이 이 구간이다."""
    orders = decide_bull_daytrade(_view({'005930': _pos(1000, partial=True)}), [], {'005930': 990})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '매입가 복귀' in sells[0]['reason']


def test_breakeven_stop_leaves_a_position_still_in_profit():
    """본전 위면 건드리지 않는다 — 원복이 익절 경로까지 자르면 안 된다."""
    orders = decide_bull_daytrade(_view({'005930': _pos(1000, partial=True)}), [], {'005930': 1001})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert sells == []


def test_entry_when_conditions_met():
    # 90→110(기간변동 22.2%)은 같지만 단조상승이 아니라 잔파도를 줘서 ADX를 상한(60) 아래로
    # 유지한다(2026-08-05 ADX 상한 도입 — 단조상승은 ADX=100이라 이제 거부된다).
    cand = [{'code': '111', 'name': '진입주', 'price': 1000, 'amount': 5_000_000_000,
             'sparkline_price': [90, 97, 92, 101, 95, 110], 'change_rate': '+3.0%',
             'orgn_fake_ntby_qty': 100, 'frgn_fake_ntby_qty': 0, 'tick_power': 130.0}]
    orders = decide_bull_daytrade(_view({}), cand, {'111': 1000})
    buys = [o for o in orders if o['action'] == 'BUY']
    assert len(buys) == 1 and buys[0]['code'] == '111'
