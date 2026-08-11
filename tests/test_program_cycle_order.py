"""정산은 심 판단보다 먼저다. 그리고 매수는 원장에 즉시 들어가지 않는다."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.program_trader import (
    settle_pending_orders, _lookup_by_pending_date, _pending_buy_cost,
    _seed_turn_basis_for_settled_buys,
)
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


def test_settle_partial_fill_across_cycles_does_not_double_apply():
    """2/3 체결 + 취소 실패 → 다음 사이클에 같은 odno가 다시 누적 체결로 조회돼도
    이미 반영된 몫이 또 더해지면 안 된다(2주 체결이 5주로 불어나는 회귀 방지)."""
    led = {'positions': {}, 'realized_pnl': 0, 'pending_orders': {
        '353200': {'odno': 'OD1', 'side': 'buy', 'qty': 3, 'price': 111000,
                   'ordered_at': 'x', 'avg_price': None, 'tag': None}}}

    # 1회차: 2/3 체결, 취소 실패 → pending이 applied_qty=2로 복원되어 남는다.
    settle_pending_orders(
        led, '2026-08-11',
        lookup=lambda odno: (FILLED, {'odno': odno, 'qty': 2, 'price': 111200}),
        cancel=lambda odno, code, qty: False,
        log=lambda *a: None, log_error=lambda *a: None,
    )
    assert led['positions']['353200']['quantity'] == 2
    assert led['pending_orders']['353200']['applied_qty'] == 2

    # 2회차: 같은 odno가 이번엔 누적 3/3(전량)으로 조회되고 취소는 필요 없어진다.
    settle_pending_orders(
        led, '2026-08-11',
        lookup=lambda odno: (FILLED, {'odno': odno, 'qty': 3, 'price': 111200}),
        cancel=lambda odno, code, qty: True,
        log=lambda *a: None, log_error=lambda *a: None,
    )

    assert led['positions']['353200']['quantity'] == 3, "누적 체결량이 중복 반영되면 안 된다"
    assert led['pending_orders'] == {}


# ---- _lookup_by_pending_date: 날짜 경계 넘는 pending 조회 ----

def test_lookup_by_pending_date_uses_ordered_at_as_from_date():
    """장 마감 직전 주문이 다음 거래일까지 안 걸리면, '오늘' 범위로만 조회해선
    안 된다 — 어제 낸 주문의 ordered_at을 조회 시작일로 넘겨야 찾는다."""
    calls = []

    def fake_lookup(odno, from_date=None, to_date=None):
        calls.append((odno, from_date, to_date))
        if from_date == '20260810':
            return (FILLED, {'odno': odno, 'qty': 3, 'price': 111000})
        return (UNFILLED, None)  # '오늘' 범위로만 조회하면 못 찾는다(오판의 원인)

    pending = {'353200': {'odno': 'OD1', 'ordered_at': '2026-08-10T15:19:00+09:00'}}
    lookup = _lookup_by_pending_date(pending, '2026-08-11', lookup_fn=fake_lookup)

    status, fill = lookup('OD1')

    assert status == FILLED
    assert fill['qty'] == 3
    assert calls == [('OD1', '20260810', '20260811')]


def test_lookup_by_pending_date_falls_back_to_today_when_odno_unmatched():
    """pending에 없는 odno는(방어적으로) 오늘 날짜로 조회한다."""
    calls = []

    def fake_lookup(odno, from_date=None, to_date=None):
        calls.append((odno, from_date, to_date))
        return (UNKNOWN, None)

    lookup = _lookup_by_pending_date({}, '2026-08-11', lookup_fn=fake_lookup)
    lookup('OD-UNKNOWN')

    assert calls == [('OD-UNKNOWN', '20260811', '20260811')]


def test_settlement_finds_fill_across_day_boundary_via_ordered_at():
    """주문일(ordered_at)이 어제인 pending을 오늘 조회해도 체결을 찾아 반영한다
    (날짜 경계에서 고착 포지션이 생기던 버그의 회귀 방지)."""
    def fake_lookup(odno, from_date=None, to_date=None):
        if from_date == '20260810':
            return (FILLED, {'odno': odno, 'qty': 3, 'price': 111000})
        return (UNFILLED, None)

    led = {'positions': {}, 'realized_pnl': 0, 'pending_orders': {
        '353200': {'odno': 'OD1', 'side': 'buy', 'qty': 3, 'price': 111000,
                   'ordered_at': '2026-08-10T15:19:00+09:00', 'avg_price': None,
                   'tag': None}}}

    lookup = _lookup_by_pending_date(led['pending_orders'], '2026-08-11', lookup_fn=fake_lookup)
    settle_pending_orders(led, '2026-08-11', lookup, cancel=lambda *a: True,
                          log=lambda *a: None, log_error=lambda *a: None)

    assert led['positions']['353200']['quantity'] == 3
    assert led['pending_orders'] == {}


# ---- _pending_buy_cost: 미체결 매수의 현금 예약 ----

def test_pending_buy_cost_sums_only_buy_side():
    pending = {
        '005930': {'side': 'buy', 'qty': 10, 'price': 70_000},
        '000660': {'side': 'sell', 'qty': 5, 'price': 100_000},
        '051900': {'side': 'buy', 'qty': 2, 'price': 300_000},
    }

    assert _pending_buy_cost(pending) == 10 * 70_000 + 2 * 300_000


def test_pending_buy_cost_empty_or_none_is_zero():
    assert _pending_buy_cost({}) == 0
    assert _pending_buy_cost(None) == 0


# ---- _seed_turn_basis_for_settled_buys: 정산 확정 매수의 턴 기준가 ----

def test_seed_turn_basis_for_new_position_uses_fill_price():
    """정산으로 새로 생긴 포지션은 체결가로 기준가가 잡혀야 한다."""
    turn = {'id': 't1', 'capital': 3_000_000, 'basis': {}, 'by_tag': {}, 'active_tag': None}
    pre_settle = {'353200': {}}  # 정산 전엔 보유하지 않았다
    positions = {'353200': {'quantity': 3, 'avg_price': 111_200}}

    _seed_turn_basis_for_settled_buys(turn, {'353200'}, pre_settle, positions)

    assert turn['basis']['353200'] == 111_200


def test_seed_turn_basis_add_on_uses_weighted_incremental_price():
    """기존 보유에 추가 체결이 붙으면, 새로 들어온 분의 가격만 뽑아 반영해야 한다."""
    turn = {'id': 't1', 'capital': 3_000_000, 'basis': {'353200': 110_000}, 'by_tag': {},
            'active_tag': None}
    pre_settle = {'353200': {'quantity': 2, 'avg_price': 110_000}}
    # 정산 후 avg_price=111,200은 기존 2주(110,000)+신규 1주 체결가의 가중평균이다.
    # 신규 1주의 체결가를 역산하면: (111,200*3 - 110,000*2)/1 = 113,600.
    # record_buy는 그 113,600을 기존 turn.basis(110,000, 2주)와 다시 가중평균한다:
    # (110,000*2 + 113,600*1)/3 = 111,200 — positions의 avg_price와 우연히 같아진다
    # (둘 다 같은 prev_qty/prev_avg에서 같은 방식으로 계산됐으므로).
    positions = {'353200': {'quantity': 3, 'avg_price': 111_200}}

    _seed_turn_basis_for_settled_buys(turn, {'353200'}, pre_settle, positions)

    assert turn['basis']['353200'] == 111_200


def test_seed_turn_basis_skips_when_no_new_fill():
    """이번 사이클에 새로 확정된 체결이 없으면(수량 변화 없음) 건드리지 않는다."""
    turn = {'id': 't1', 'capital': 3_000_000, 'basis': {}, 'by_tag': {}, 'active_tag': None}
    pre_settle = {'353200': {'quantity': 3, 'avg_price': 111_200}}
    positions = {'353200': {'quantity': 3, 'avg_price': 111_200}}  # 변화 없음

    _seed_turn_basis_for_settled_buys(turn, {'353200'}, pre_settle, positions)

    assert '353200' not in turn['basis']


def test_seed_turn_basis_noop_when_turn_falsy():
    """턴 회계가 꺼져 있으면(turn={}) 아무 것도 하지 않는다 — 예외도 없어야 한다."""
    positions = {'353200': {'quantity': 3, 'avg_price': 111_200}}

    _seed_turn_basis_for_settled_buys({}, {'353200'}, {'353200': {}}, positions)  # 예외 없이 통과
