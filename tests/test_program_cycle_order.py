"""정산은 심 판단보다 먼저다. 그리고 매수는 원장에 즉시 들어가지 않는다."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.program_trader import settle_pending_orders
from src.trade.executions import FILLED, UNFILLED, UNKNOWN


def test_settle_applies_fills_and_cancels_remainder():
    led = {'positions': {}, 'realized_pnl': 0, 'pending_orders': {
        '353200': {'odno': 'OD1', 'side': 'buy', 'qty': 3, 'price': 111000,
                   'ordered_at': 'x', 'avg_price': None, 'tag': None}}}
    cancelled = []

    settle_pending_orders(
        led, '2026-08-11',
        lookup=lambda odno: (FILLED, {'odno': odno, 'qty': 2, 'price': 111200}),
        cancel=lambda odno, code, qty: cancelled.append((odno, code, qty)) or True,
        log=lambda *a: None, log_error=lambda *a: None,
    )

    assert led['positions']['353200']['quantity'] == 2
    assert cancelled == [('OD1', '353200', 1)]
    assert led['pending_orders'] == {}


def test_failed_cancel_keeps_pending_so_no_new_order_goes_out():
    """취소 실패 → 그 종목에 새 주문을 내지 않는다. 중복보다 기회손실이 싸다."""
    led = {'positions': {}, 'realized_pnl': 0, 'pending_orders': {
        '353200': {'odno': 'OD1', 'side': 'buy', 'qty': 3, 'price': 111000,
                   'ordered_at': 'x', 'avg_price': None, 'tag': None}}}

    settle_pending_orders(
        led, '2026-08-11',
        lookup=lambda odno: (UNFILLED, None),
        cancel=lambda odno, code, qty: False,
        log=lambda *a: None, log_error=lambda *a: None,
    )

    assert '353200' in led['pending_orders']


def test_unknown_lookup_keeps_pending_and_skips_cancel():
    led = {'positions': {}, 'realized_pnl': 0, 'pending_orders': {
        '353200': {'odno': 'OD1', 'side': 'buy', 'qty': 3, 'price': 111000,
                   'ordered_at': 'x', 'avg_price': None, 'tag': None}}}
    cancelled = []

    settle_pending_orders(
        led, '2026-08-11',
        lookup=lambda odno: (UNKNOWN, None),
        cancel=lambda odno, code, qty: cancelled.append(odno) or True,
        log=lambda *a: None, log_error=lambda *a: None,
    )

    assert '353200' in led['pending_orders']
    assert cancelled == []
