"""심9가 왜 안 사는지를 심 스스로 말하게 만든다.

2026-08-13 심 전체 감사: sim_gapfade는 배포 이래 매수가 **0건**이다(리셋 직전
현금이 정확히 3,000,000원). 그런데 로그에는 아무것도 안 남아서 "신호가 없는
날"과 "구조적으로 못 사는 심"이 구분되지 않았다.

의심: 유니버스와 진입 조건이 서로 밀어낸다.
  - 유니버스 = KOSPI **상승률 상위 50**(get_fluctuation_rank sort='0')
  - 진입 = 갭 >= +7% AND 장중 되밀림 <= -6%
  - 그 종목의 당일 등락률 = 1.07 x 0.94 - 1 = **+0.58% 이하**

+0.58%짜리 종목은 정상적인 날 상승률 상위 50에 못 든다. 다만 하락장에서는
50위가 0% 근처일 수 있어 원리적으로 불가능하진 않다 — 그래서 추측으로
유니버스를 바꾸지 않고 **먼저 센다.**

`gap` 탈락이 후보 전량이면 유니버스 문제가 확정된다. gap을 통과하는 종목이
매일 몇 개씩 나오는데 뒤 게이트에서 죽으면 원인은 다른 데 있다.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy.simulators.sim9_gap_fade import decide_gap_fade

ENTRY_TIME = datetime(2026, 8, 14, 14, 45)   # 진입 창(14:30~15:20) 안
BIG = 5_000_000_000


def _view():
    return {'nav': 3_000_000, 'portfolio': {}, 'cooldown_codes': {}}


def _stock(code='005930', prev=10000, gap_pct=8.0, intra_pct=-7.0, pos=0.1,
           amount=BIG):
    open_px = prev * (1 + gap_pct / 100)
    price = open_px * (1 + intra_pct / 100)
    # 일중 위치가 pos가 되도록 고가/저가를 만든다.
    lo = price - 100
    hi = lo + (100 / pos if pos else 1000)
    return {'code': code, 'name': '테스트', 'price': price, 'open_price': open_px,
            'prev_close': prev, 'amount': amount, 'day_high': hi, 'day_low': lo}


def _run(stocks):
    funnel = []
    orders = decide_gap_fade(_view(), stocks, {}, now=ENTRY_TIME, funnel=funnel)
    return orders, funnel


def test_a_qualifying_stock_is_bought():
    """깔때기를 붙이면서 진입 자체를 깨지 않았는지 먼저 고정한다."""
    orders, _ = _run([_stock()])

    assert [o['action'] for o in orders] == ['BUY']


def test_gap_rejection_is_recorded():
    """유니버스 의심을 확정하려면 이 카운트가 필요하다."""
    _, funnel = _run([_stock(gap_pct=1.0)])

    assert [f['reason'] for f in funnel] == ['gap']
    assert round(funnel[0]['gap'], 1) == 1.0


def test_intra_rejection_is_recorded_with_values():
    """갭은 통과했는데 되밀림이 모자란 경우. 이게 매일 몇 건씩 나오면
    원인은 유니버스가 아니라 조건 강도다."""
    _, funnel = _run([_stock(gap_pct=8.0, intra_pct=-1.0)])

    assert funnel[0]['reason'] == 'intra'
    assert round(funnel[0]['gap'], 1) == 8.0
    assert round(funnel[0]['intra'], 1) == -1.0


def test_range_position_rejection_is_recorded():
    _, funnel = _run([_stock(pos=0.9)])

    assert funnel[0]['reason'] == 'range_pos'
    assert funnel[0]['pos'] > 0.2


def test_amount_and_ohlc_gates_are_distinguished():
    """'거래대금 미달'과 '시가/전일종가를 못 받았다'는 원인이 다르다.
    한 덩어리로 세면 데이터 결손이 조건 미달로 위장된다."""
    _, funnel = _run([_stock(code='A', amount=1),
                      {'code': 'B', 'price': 100, 'amount': BIG}])

    reasons = {f['code']: f['reason'] for f in funnel}
    assert reasons['A'] == 'amount'
    assert reasons['B'] == 'no_ohlc'


def test_funnel_is_optional():
    """운영 경로 밖(백테스트 등)에서 funnel 없이 불러도 깨지지 않는다."""
    orders = decide_gap_fade(_view(), [_stock()], {}, now=ENTRY_TIME)

    assert [o['action'] for o in orders] == ['BUY']
