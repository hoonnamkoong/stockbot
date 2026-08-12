"""같은 가격으로 오래 안 체결되는 미체결 주문을 사람에게 올린다.

2026-08-04 설계의 Success Criteria 2번 — "판단가가 런 사이에 얼어붙지 않는다.
같은 종목의 판단가가 연속 3런 이상 동일하면 경보" — 아홉 항목 중 **이것만
구현이 빠졌다.** 그리고 8일 뒤(08-12) 001210이 판단가 5,300원으로 수백 런 고착된
채 취소→재주문을 반복했고, 경보는 한 번도 울리지 않았다.

PR #28이 피해(대기열 리셋)는 막았지만 **감지**는 여전히 없다. 오히려 #28 이후로는
주문이 대기열에 남으므로, 심이 더는 원하지 않는 주문이 조용히 예산을 묶을 수 있다 —
그걸 드러내는 것이 이 경보다.

임계값은 시간으로 잰다. 설계 당시 트리거가 10분 주기라 "3런"이 30분이었는데,
지금은 2분 주기라 3런이면 6분이다. 지정가가 6분 안 체결되지 않는 건 정상이라
런 수로 재면 경보가 무의미해진다.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime

from src.pipeline.workers.program_trader import settle_pending_orders, STUCK_ORDER_MIN
from src.trade.executions import UNFILLED

TODAY = '2026-08-12'
ORDERED_AT = f'{TODAY}T09:22:43'


def _ledger(ordered_at=ORDERED_AT):
    return {
        'positions': {},
        'pending_orders': {
            '001210': {'odno': 'OD1', 'side': 'buy', 'qty': 31, 'price': 5300,
                       'ordered_at': ordered_at, 'avg_price': None, 'tag': None,
                       'snapshot': {}, 'applied_qty': 0},
        },
    }


class _AlertSpy:
    def __init__(self):
        self.calls = []

    def __call__(self, key, text, now, **kw):
        self.calls.append((key, text))
        return True


def _settle(ledger, now_kst, alert, live=5300):
    settle_pending_orders(ledger, TODAY, lambda odno: (UNFILLED, None),
                          lambda *a: True, lambda m: None, lambda m: None,
                          now_kst=now_kst, alert=alert,
                          quote=lambda code: {'price': live})


def test_no_alert_before_the_threshold():
    """막 낸 주문이 아직 안 체결된 건 정상이다."""
    alert = _AlertSpy()
    _settle(_ledger(), datetime(2026, 8, 12, 9, 40), alert)   # 17분 경과
    assert alert.calls == []


def test_alert_when_the_order_sits_at_the_same_price_too_long():
    alert = _AlertSpy()
    _settle(_ledger(), datetime(2026, 8, 12, 11, 0), alert)   # 97분 경과
    assert len(alert.calls) == 1
    key, text = alert.calls[0]
    assert '001210' in key
    assert '001210' in text and '5,300' in text


def test_threshold_matches_the_original_thirty_minute_intent():
    """설계의 '연속 3런'은 10분 주기 시절의 30분이었다."""
    assert STUCK_ORDER_MIN == 30


def test_no_alert_when_the_order_is_being_cancelled():
    """가격이 움직여 거둬들이는 주문은 고착이 아니다."""
    alert = _AlertSpy()
    _settle(_ledger(), datetime(2026, 8, 12, 11, 0), alert, live=5210)
    assert alert.calls == []


def test_unparsable_timestamp_does_not_crash_or_alert():
    """주문 시각을 못 읽으면 조용히 넘어간다 — 모르는 걸 장애로 부르지 않는다."""
    alert = _AlertSpy()
    led = _ledger(ordered_at='(없음)')
    _settle(led, datetime(2026, 8, 12, 11, 0), alert)
    assert alert.calls == []
    assert '001210' in led['pending_orders'], '경보 실패가 주문 유지를 깨면 안 된다'
