"""pending 정산 — 주문과 체결을 가르는 지점.

이 함수가 틀리면 원장이 실계좌와 갈린다. 매수는 체결 전까지 원장에 없고,
매도는 추정으로 먼저 반영된 뒤 실측으로 정정된다는 비대칭이 핵심이다.

조회 실패(unknown)를 미체결로 오인하면 팔린 포지션이 되살아난다. 그래서
unknown은 어떤 경우에도 원장을 건드리지 않는다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.trade.executions import FILLED, UNFILLED, UNKNOWN
from src.trade.fees import realized_pnl_after_fees
from src.trade.pending import reconcile_pending, register_pending

TODAY = '2026-08-11'


def _fill(qty, price, odno='OD1'):
    return {'odno': odno, 'qty': qty, 'price': price}


def _buy_ledger():
    led = {'positions': {}, 'realized_pnl': 0}
    register_pending(led, '353200', 'OD1', 'buy', 3, 111000, '2026-08-11T09:20:31')
    return led


def _sell_ledger():
    """매도는 주문 시 추정으로 이미 반영된 상태다(applied)."""
    led = {'positions': {}, 'realized_pnl': realized_pnl_after_fees(1, 111500, 107900)}
    register_pending(led, '353200', 'OD1', 'sell', 1, 107900, '2026-08-11T09:44:31',
                     avg_price=111500)
    return led


# ---- 매수 ----

def test_buy_filled_enters_positions_at_measured_price():
    led = _buy_ledger()

    cancels = reconcile_pending(led, {'OD1': (FILLED, _fill(3, 111200))}, TODAY)

    assert led['positions']['353200']['quantity'] == 3
    assert led['positions']['353200']['avg_price'] == 111200, '주문가가 아니라 체결 실측가'
    assert cancels == []
    assert led['pending_orders'] == {}


def test_buy_unfilled_leaves_ledger_untouched_and_asks_cancel():
    led = _buy_ledger()

    cancels = reconcile_pending(led, {'OD1': (UNFILLED, None)}, TODAY)

    assert led['positions'] == {}
    assert cancels == [{'odno': 'OD1', 'code': '353200', 'qty': 3}]


def test_buy_partial_enters_filled_part_and_cancels_remainder():
    led = _buy_ledger()

    cancels = reconcile_pending(led, {'OD1': (FILLED, _fill(2, 111200))}, TODAY)

    assert led['positions']['353200']['quantity'] == 2
    assert cancels == [{'odno': 'OD1', 'code': '353200', 'qty': 1}]


def test_buy_unknown_keeps_pending_and_asks_nothing():
    """조회 실패 — 다음 사이클에 다시 본다. 취소도 하지 않는다."""
    led = _buy_ledger()

    cancels = reconcile_pending(led, {'OD1': (UNKNOWN, None)}, TODAY)

    assert led['positions'] == {}
    assert cancels == []
    assert '353200' in led['pending_orders'], 'pending이 남아야 중복 주문이 막힌다'


# ---- 매도 ----

def test_sell_filled_corrects_to_measured_price():
    led = _sell_ledger()

    reconcile_pending(led, {'OD1': (FILLED, _fill(1, 108000))}, TODAY)

    assert led['realized_pnl'] == realized_pnl_after_fees(1, 111500, 108000)
    assert '353200' not in led['positions']


def test_sell_unfilled_restores_position_and_undoes_pnl():
    """시장가가 안 잡히는 경우(거래정지·하한가). 원장이 거짓말하면 고착 포지션이 된다."""
    led = _sell_ledger()

    reconcile_pending(led, {'OD1': (UNFILLED, None)}, TODAY)

    assert led['realized_pnl'] == 0
    assert led['positions']['353200']['quantity'] == 1
    assert led['positions']['353200']['avg_price'] == 111500


def test_sell_partial_restores_only_unfilled_quantity():
    led = {'positions': {}, 'realized_pnl': realized_pnl_after_fees(10, 111500, 107900)}
    register_pending(led, '353200', 'OD1', 'sell', 10, 107900, '2026-08-11T09:44:31',
                     avg_price=111500)

    reconcile_pending(led, {'OD1': (FILLED, _fill(6, 108000))}, TODAY)

    assert led['realized_pnl'] == realized_pnl_after_fees(6, 111500, 108000)
    assert led['positions']['353200']['quantity'] == 4


def test_sell_unknown_keeps_everything_frozen():
    led = _sell_ledger()
    before = led['realized_pnl']

    reconcile_pending(led, {'OD1': (UNKNOWN, None)}, TODAY)

    assert led['realized_pnl'] == before
    assert led['positions'] == {}
    assert '353200' in led['pending_orders']


def test_sell_unfilled_restore_uses_snapshot_for_entry_date_and_scaled_out():
    """매도 주문 시 positions[code]는 이미 지워져 있다(Task 6의 정상 경로).

    entry_date·is_scaled_out은 pending 엔트리 자체엔 없어서, register_pending이
    받아 둔 snapshot(매도 직전 원래 포지션)이 없으면 빈 값/False로 리셋된다.
    """
    led = {'positions': {}, 'realized_pnl': realized_pnl_after_fees(1, 111500, 107900)}
    register_pending(led, '353200', 'OD1', 'sell', 1, 107900, '2026-08-11T09:44:31',
                     avg_price=111500,
                     snapshot={'entry_date': '2026-07-01', 'is_scaled_out': True,
                               'peak_price': 115000, 'name': '심리괴리'})

    reconcile_pending(led, {'OD1': (UNFILLED, None)}, TODAY)

    pos = led['positions']['353200']
    assert pos['entry_date'] == '2026-07-01'
    assert pos['is_scaled_out'] is True
    assert pos['peak_price'] == 115000
    assert pos['name'] == '심리괴리'
    assert pos['quantity'] == 1
    assert pos['avg_price'] == 111500


def test_sell_partial_restore_uses_snapshot_when_no_snapshot_defaults_are_empty():
    """snapshot을 안 넘기면(기존 호출부) 예전과 같이 빈 값/False로 떨어진다 — 회귀 없음."""
    led = {'positions': {}, 'realized_pnl': realized_pnl_after_fees(10, 111500, 107900)}
    register_pending(led, '353200', 'OD1', 'sell', 10, 107900, '2026-08-11T09:44:31',
                     avg_price=111500)

    reconcile_pending(led, {'OD1': (FILLED, _fill(6, 108000))}, TODAY)

    pos = led['positions']['353200']
    assert pos['quantity'] == 4
    assert pos['entry_date'] == ''
    assert pos['is_scaled_out'] is False


# ---- 공통 ----

def test_missing_lookup_is_treated_as_unknown():
    """조회 결과에 아예 없는 주문번호를 미체결로 단정하면 안 된다."""
    led = _buy_ledger()

    cancels = reconcile_pending(led, {}, TODAY)

    assert cancels == []
    assert '353200' in led['pending_orders']


def test_register_rejects_second_order_for_same_code():
    """종목당 1건 — 이 제약이 중복 주문 방지의 근거다."""
    led = _buy_ledger()

    register_pending(led, '353200', 'OD2', 'buy', 5, 112000, '2026-08-11T09:22:31')

    assert led['pending_orders']['353200']['odno'] == 'OD1', '기존 주문을 덮어쓰면 안 된다'
