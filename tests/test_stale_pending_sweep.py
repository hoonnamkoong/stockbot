"""조회가 안 되는 어제 주문이 원장에 영원히 남지 않게 만든다.

2026-08-13 발견: 001210의 미체결 매수(34주 @ 5,300, 08-12T15:29 주문)가 다음
거래일 15:31까지 pending에 그대로 남아 180,200원을 묶고 있었다. 그동안 그 종목은
`pending_codes`에 걸려 신규 매수도 막힌다.

`settle_pending_orders`에는 이미 날짜 경계 탈출구가 있다 — "어제 이전 주문의
취소가 실패하면 pending에서 제거하고 사람에게 알린다". 그런데 그 자리에
**도달할 수가 없다.** `reconcile_pending`은 조회 결과가 UNKNOWN이면 `continue`로
빠지므로 취소 목록에 오르지 않고, 따라서 취소를 시도하지도, 날짜 경계 분기에
닿지도 못한다. UNKNOWN이 한 번 굳으면 그 pending은 불멸이 된다.

그래서 조회 성공 여부와 **무관하게** 쓸어내는 자리가 필요하다. KRX 정규 주문은
장 마감에 소멸한다 — 어제 낸 지정가가 오늘도 pending인 건, 조회가 되든 안 되든
원장이 현실과 어긋났다는 뜻이다.

지어내지 않는다: 제거하면서 사람에게 "체결 내역을 직접 확인하라"고 알린다.
못 본 체결이 있었다면 실계좌엔 포지션이 있는데 원장엔 없는 상태이고, 그건
사람만 풀 수 있다.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.workers.program_trader import settle_pending_orders
from src.trade.executions import UNKNOWN

TODAY = '2026-08-13'


class _AlertSpy:
    def __init__(self):
        self.calls = []

    def __call__(self, key, text, now, **kw):
        self.calls.append((key, text))
        return True


def _ledger(ordered_at, side='buy', applied_qty=0):
    return {
        'positions': {},
        'pending_orders': {
            '001210': {'odno': 'OD1', 'side': side, 'qty': 34, 'price': 5300.0,
                       'ordered_at': ordered_at, 'avg_price': None, 'tag': None,
                       'snapshot': {}, 'applied_qty': applied_qty},
        },
    }


def _settle(ledger, alert, lookup=lambda odno: (UNKNOWN, None)):
    """조회가 UNKNOWN인 경로 — 001210이 실제로 갇혀 있던 그 경로다."""
    settle_pending_orders(ledger, TODAY, lookup,
                          lambda *a: True, lambda m: None, lambda m: None,
                          now_kst=datetime(2026, 8, 13, 9, 5), alert=alert,
                          quote=lambda code: {'price': 5300})


def test_yesterdays_unknown_order_is_swept():
    """08-13 실제 상황. 여기가 이 변경의 목적이다."""
    ledger = _ledger('2026-08-12T15:29:21')
    alert = _AlertSpy()

    _settle(ledger, alert)

    assert ledger['pending_orders'] == {}


def test_sweeping_tells_a_human_to_check_the_broker():
    """조회가 안 되는 채로 지웠다. 못 본 체결이 있었다면 실계좌엔 포지션이
    있는데 원장엔 없다 — 사람만 풀 수 있는 상태다."""
    ledger = _ledger('2026-08-12T15:29:21')
    alert = _AlertSpy()

    _settle(ledger, alert)

    assert len(alert.calls) == 1
    key, text = alert.calls[0]
    assert '001210' in key
    assert 'OD1' in text


def test_todays_unknown_order_is_left_alone():
    """오늘 낸 주문은 아직 살아 있다. 조회 실패로 지우면 방금 낸 주문을
    원장에서 잃고, 그러면 같은 종목을 또 산다(이중 지출)."""
    ledger = _ledger(f'{TODAY}T09:03:11')
    alert = _AlertSpy()

    _settle(ledger, alert)

    assert '001210' in ledger['pending_orders']
    assert alert.calls == []


def test_sweep_does_not_touch_positions():
    """부분체결분은 이미 positions에 반영돼 있다. 쓸어내기가 그걸 건드리면
    실제로 보유한 주식이 원장에서 사라진다."""
    ledger = _ledger('2026-08-12T15:29:21', applied_qty=10)
    ledger['positions']['001210'] = {'quantity': 10, 'avg_price': 5300.0}
    alert = _AlertSpy()

    _settle(ledger, alert)

    assert ledger['positions']['001210']['quantity'] == 10


def test_unparsable_ordered_at_is_not_swept():
    """시각을 못 읽는 것과 '어제 주문이다'는 다르다. 모르는 것을 근거로
    원장을 지우지 않는다.

    빈 문자열만으로는 부족하다 — 문자열 비교로 때우면 '(없음)' 같은 값이
    어떤 날짜보다도 작아서 조용히 '어제 주문'이 된다(실제로 그렇게 짰다가
    기존 테스트에 걸렸다)."""
    for bad in ('', '(없음)', 'unknown', '2026-13-99'):
        ledger = _ledger(bad)
        alert = _AlertSpy()

        _settle(ledger, alert)

        assert '001210' in ledger['pending_orders'], bad
        assert alert.calls == [], bad


def test_sell_side_is_swept_too():
    """매도 pending도 같은 이유로 갇힌다 — 남아 있으면 그 종목을 다시 팔지
    못하고 실현손익이 추정가로 고정된다."""
    ledger = _ledger('2026-08-12T15:29:21', side='sell')
    alert = _AlertSpy()

    _settle(ledger, alert)

    assert ledger['pending_orders'] == {}
