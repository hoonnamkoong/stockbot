"""판단가가 그대로면 미체결 매수를 거두지 않는다.

2026-08-12 실측: 001210이 상한가(5,300원)에 고정돼 판단가가 하루 종일 움직이지
않았는데, 봇이 매 사이클 취소→**동일가** 재주문을 반복했다. 지정가는 가격-시간
우선이라 재주문할 때마다 같은 가격대 대기열의 맨 뒤로 간다 — 상한가는 대기열이
가장 두꺼운 자리다. 봇이 매 분 스스로 순번을 리셋했고 체결은 0건이었다.
같은 날 002990은 09:22 첫 주문이 그대로 체결됐다(재주문을 겪지 않은 주문이었다).

설계는 "매 사이클 미체결을 취소하고 **새 판단가**로 다시 낸다"였는데
(docs/superpowers/plans/2026-08-10-limit-order-fill-confirmation.md), 판단가가
안 바뀌는 국면을 고려하지 않았다. 같은 가격이면 취소·재주문은 순수 손실이다.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.program_trader import settle_pending_orders
from src.trade.executions import UNFILLED

TODAY = '2026-08-12'


def _ledger(side='buy', price=5300):
    return {
        'positions': {},
        'pending_orders': {
            '001210': {'odno': 'OD1', 'side': side, 'qty': 31, 'price': price,
                       'ordered_at': f'{TODAY}T09:22:43', 'avg_price': 4000 if side == 'sell' else None,
                       'tag': None, 'snapshot': {}, 'applied_qty': 0},
        },
    }


class _Spy:
    def __init__(self):
        self.cancelled = []

    def __call__(self, odno, code, qty):
        self.cancelled.append((odno, code, qty))
        return True


def _settle(ledger, quote, cancel):
    settle_pending_orders(ledger, TODAY, lambda odno: (UNFILLED, None),
                          cancel, lambda m: None, lambda m: None, quote=quote)


def test_unchanged_price_keeps_the_order_resting():
    """같은 가격이면 취소하지 않는다 — 대기열 순번을 지킨다."""
    led = _ledger(price=5300)
    cancel = _Spy()

    _settle(led, lambda code: {'price': 5300}, cancel)

    assert cancel.cancelled == [], '동일가에서는 취소하면 안 된다'
    assert '001210' in led['pending_orders'], 'pending이 유지돼야 재주문도 막힌다'


def test_price_above_the_limit_still_cancels():
    """시장이 내 지정가 위로 갔다 = 이 가격엔 안 붙는다. 거두고 다시 낸다."""
    led = _ledger(price=5300)
    cancel = _Spy()

    _settle(led, lambda code: {'price': 5390}, cancel)

    assert cancel.cancelled == [('OD1', '001210', 31)]
    assert '001210' not in led['pending_orders']


def test_price_below_the_limit_keeps_resting():
    """[2026-08-13 추가] 매수 지정가 5,300에 현재가 5,210은 **체결 직전**이다.
    그걸 취소하고 5,210에 다시 내면 앞줄을 버리고 맨 뒤로 간다.

    원래 조건은 `int(live) != int(지정가)` 하나뿐이라 유리하게 움직인 경우도
    취소했다 — 사용자가 한투 앱에서 본 대량 취소의 주된 몫이 이것이다.
    `check_buy_drift`는 "상승 괴리만 막는다. 판단가보다 싸진 것은 불리하지
    않다"고 명시하는데, 이쪽엔 그 대칭이 없었다."""
    led = _ledger(price=5300)
    cancel = _Spy()

    _settle(led, lambda code: {'price': 5210}, cancel)

    assert cancel.cancelled == [], '체결 임박한 주문을 취소하면 안 된다'
    assert '001210' in led['pending_orders']


def test_quote_failure_falls_back_to_cancelling():
    """시세를 모르면 기존 동작(취소)으로 떨어진다 — 모르는 상태로 주문을 남기지 않는다."""
    led = _ledger(price=5300)
    cancel = _Spy()

    def _boom(code):
        raise RuntimeError('KIS 조회 실패')

    _settle(led, _boom, cancel)

    assert cancel.cancelled == [('OD1', '001210', 31)]


def test_zero_quote_falls_back_to_cancelling():
    """0은 가격이 아니다 — 동일가로 오인해 주문을 방치하면 안 된다."""
    led = _ledger(price=5300)
    cancel = _Spy()

    _settle(led, lambda code: {'price': 0}, cancel)

    assert cancel.cancelled == [('OD1', '001210', 31)]


def test_sell_pending_is_unaffected():
    """매도는 시장가라 대기열 논점이 없다 — 기존 경로 그대로."""
    led = _ledger(side='sell', price=5300)
    cancel = _Spy()

    _settle(led, lambda code: {'price': 5300}, cancel)

    assert cancel.cancelled == [], '매도는 reconcile이 취소 요청 자체를 만들지 않는다'
    assert '001210' not in led['pending_orders'], '매도 pending은 정산 후 지워진다'
