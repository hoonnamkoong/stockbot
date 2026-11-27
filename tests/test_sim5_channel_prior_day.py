"""[심5] 채널·RSI2는 '당일 제외' 직전 종가로 만든다(설계서 7절).

예전 생산자는 당일 행을 채널 이력에 넣었다. 하락일엔 당일 종가가 채널 저점 자체가 되어
'저점 +3% 이내'가 저절로 통과하고, 채널 폭 게이트도 쉬워지며, 청산의 rsi2(hist+[cur])는
당일을 두 번 셌다. 여기서는 날짜 붙은 price_history(계약)에서 오늘 행을 빼고 읽는지 고정한다.

픽스처 여유(경계값에 얹지 않는다):
- BOX(직전 20일): 저점 1000 / 고점 1200 → 폭 20.0% (MIN_WIDTH_PCT 8.0과 12.0%p),
  현재가 1000 = 저점 +0.0% (LOW_ZONE +3%와 3.0%p), 당일 등락 +0.5% (DAILY_CRASH -2.0과 2.5%p),
  RSI2 = 4.14 (ENTRY_RSI2_MAX 15와 10.9 차이).
- 좁은 채널: 직전 20일 1000~1060 → 폭 6.0% (MIN_WIDTH_PCT와 2.0%p 아래),
  당일 행(950)을 넣으면 폭 11.6% (3.6%p 위) — 오직 당일 포함 여부만 갈린다.
- 과열 청산: 직전 20일 1000→1019 상승 뒤 현재가 1100 → RSI2 100.0 (EXIT_RSI2_MIN 70과 30 차이).
"""
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.core import clock
from src.strategy.simulators import sim5_sideways_swing as s5
from src.strategy.simulators.sim5_sideways_swing import decide_sideways

# 직전 20일: 저점 1000 / 고점 1200, 끝으로 내려와 과매도.
BOX = [1100, 1200, 1150, 1200, 1100, 1180, 1050, 1160, 1100, 1200,
       1150, 1190, 1100, 1160, 1080, 1060, 1040, 1025, 1010, 1000]


def _today():
    return clock.date_compact()


def _rows(closes, today_close=None):
    """과거 날짜(2020년)로 연속 부여한 이력. today_close가 있으면 오늘 행을 맨 끝에 붙인다."""
    start = date(2020, 1, 1)
    rows = [{'date': (start + timedelta(days=i)).strftime('%Y%m%d'), 'close': c}
            for i, c in enumerate(closes)]
    if today_close is not None:
        rows.append({'date': _today(), 'close': today_close})
    return rows


def _view(portfolio=None, price_history=None):
    v = {'portfolio': portfolio or {}, 'cash': 3_000_000, 'initial_cash': 3_000_000,
         'nav': 3_000_000, 'cooldown_codes': {}}
    if price_history is not None:
        v['price_history'] = price_history
    return v


def _stock(rows, code='222', price=1000):
    return {'code': code, 'name': f'레인지{code}', 'price': price, 'amount': 2_000_000_000,
            'price_history': rows, 'change_rate': '+0.5%'}


def _pos(avg, days_ago=0):
    return {'name': 'T', 'quantity': 10, 'avg_price': avg, 'peak_price': avg,
            'entry_date': (date.today() - timedelta(days=days_ago)).isoformat()}


def _buys(orders):
    return [o for o in orders if o['action'] == 'BUY']


def _sells(orders):
    return [o for o in orders if o['action'] == 'SELL']


def _spy_rsi2(monkeypatch):
    calls = []
    real = s5.rsi2

    def spy(closes):
        calls.append(list(closes))
        return real(closes)
    monkeypatch.setattr(s5, 'rsi2', spy)
    return calls


def test_channel_excludes_today_even_when_today_is_the_low():
    """직전 채널은 1000~1060(폭 6%)로 좁다. 하락일 당일 행(950)이 채널에 들면 폭이 11.6%로
    벌어져 게이트를 넘는다 — 당일을 빼면 narrow_channel로 막혀야 한다."""
    prior = [1000, 1060] * 10
    funnel = []
    orders = decide_sideways(_view(), [_stock(_rows(prior, today_close=950), price=950)],
                             {'222': 950}, funnel=funnel, allow_entry=True)
    assert _buys(orders) == []
    assert [f['reason'] for f in funnel] == ['narrow_channel']
    assert funnel[0]['width'] == pytest.approx(6.0)


def test_channel_window_stays_20_with_25_rows():
    """25행(직전 24 + 당일)을 받아도 채널은 직전 20일이다 — 전략 상수를 바꾸지 않는다.
    가장 오래된 4행의 극단값(500·2000 등)이 low/high에 들어가면 폭이 달라지고 진입이 막힌다."""
    old_extremes = [500, 2000, 1500, 600]
    rows = _rows(old_extremes + BOX, today_close=1000)
    assert len(rows) == 25
    orders = decide_sideways(_view(), [_stock(rows)], {'222': 1000}, allow_entry=True)
    b = _buys(orders)
    assert len(b) == 1
    assert '채널폭 20.0%' in b[0]['reason']      # 저점 1000 / 고점 1200 = 정확히 20일 구간


def test_rsi2_counts_today_once_on_entry(monkeypatch):
    """이력에 든 당일 행(1005)은 RSI2에 들어가지 않고, 현재가(1000)가 정확히 한 번 붙는다."""
    calls = _spy_rsi2(monkeypatch)
    rows = _rows(BOX, today_close=1005)
    decide_sideways(_view(), [_stock(rows)], {'222': 1000}, allow_entry=True)
    assert calls == [BOX + [1000]]
    assert len(calls[0]) == 21


def test_rsi2_counts_today_once_on_exit(monkeypatch):
    calls = _spy_rsi2(monkeypatch)
    rows = _rows(BOX, today_close=1005)
    cand = [_stock(rows, code='005930', price=1000)]
    decide_sideways(_view({'005930': _pos(1000)}), cand, {'005930': 1000}, allow_entry=False)
    assert calls == [BOX + [1000]]


def test_exit_reads_history_supplied_by_view_for_holding_outside_candidates():
    """보유가 후보 밖으로 밀려나도 view 공급분으로 RSI2 과열 청산이 난다."""
    rising = [1000 + i for i in range(20)]
    ph = {'005930': _rows(rising, today_close=1100)}
    orders = decide_sideways(_view({'005930': _pos(1000)}, price_history=ph), [],
                             {'005930': 1100}, allow_entry=False)
    s = _sells(orders)
    assert len(s) == 1 and 'RSI2 과열' in s[0]['reason']


def test_entry_possible_with_25_rows_and_blocked_with_20():
    """회귀 가드: 20행이면 당일 제외 후 19행이라 채널이 안 선다. 25행(직전 24)은 진입한다."""
    funnel20 = []
    rows20 = _rows(BOX[1:], today_close=1000)
    assert len(rows20) == 20
    o20 = decide_sideways(_view(), [_stock(rows20)], {'222': 1000},
                          funnel=funnel20, allow_entry=True)
    assert _buys(o20) == []
    assert [f['reason'] for f in funnel20] == ['no_channel']

    rows25 = _rows([1100, 1150, 1100, 1120] + BOX, today_close=1000)
    assert len(rows25) == 25
    funnel25 = []
    o25 = decide_sideways(_view(), [_stock(rows25)], {'222': 1000},
                          funnel=funnel25, allow_entry=True)
    assert len(_buys(o25)) == 1 and funnel25 == []


def test_exit_rsi2_skipped_without_history_but_hard_stop_fires(monkeypatch, capsys):
    calls = _spy_rsi2(monkeypatch)
    # 이력 없음 + -6%: 하드 손절은 난다.
    o = decide_sideways(_view({'005930': _pos(1000)}), [], {'005930': 940}, allow_entry=False)
    assert len(_sells(o)) == 1 and '하드 손절' in _sells(o)[0]['reason']
    # 이력 없음 + -1%: 판정 불가를 알리고 아무것도 하지 않는다(값을 지어내지 않는다).
    o = decide_sideways(_view({'005930': _pos(1000)}), [], {'005930': 990}, allow_entry=False)
    assert _sells(o) == []
    assert '판정 불가' in capsys.readouterr().out
    # 직전 19일뿐인 이력(오늘 행 포함 20행)도 같은 결손으로 본다.
    short = [_stock(_rows(BOX[1:], today_close=990), code='005930', price=990)]
    o = decide_sideways(_view({'005930': _pos(1000)}), short, {'005930': 990}, allow_entry=False)
    assert _sells(o) == []
    assert calls == []        # RSI2는 한 번도 계산되지 않았다
