"""턴 수수료 누적 — 화면의 '수수료 N원 차감'이 손익에서 실제로 뺀 값과 같아야 한다."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.program_trader import accrue_realized_pnl
from src.trade.fees import roundtrip_cost
from src.trade.pending import _correct_sell


def _ledger():
    return {'realized_pnl': 0.0, 'turn': {'id': 't1', 'by_tag': {}, 'fees_realized': 0.0}}


def test_sell_order_accrues_estimated_fees():
    led = _ledger()
    positions = {'005930': {'avg_price': 1000.0, 'quantity': 10}}

    accrue_realized_pnl(led, positions, '005930', 10, 1100.0)

    assert led['turn']['fees_realized'] == roundtrip_cost(10, 1000.0, 1100.0)


def test_settlement_corrects_fees_to_actual():
    """전량 주문했는데 6주만 체결 — 수수료도 6주분으로 줄어야 한다."""
    led = _ledger()
    positions = {}
    led['turn']['fees_realized'] = roundtrip_cost(10, 1000.0, 1100.0)
    p = {'qty': 10, 'price': 1100.0, 'avg_price': 1000.0, 'tag': 'sim4'}

    _correct_sell(led, positions, '005930', p, filled_qty=6, fill_px=1090.0)

    assert abs(led['turn']['fees_realized'] - roundtrip_cost(6, 1000.0, 1090.0)) < 1e-9


def test_unfilled_sell_removes_the_accrued_fee():
    """한 주도 안 팔렸으면 비용도 0으로 되돌아간다 — 안 낸 돈이 남으면 안 된다."""
    led = _ledger()
    led['turn']['fees_realized'] = roundtrip_cost(10, 1000.0, 1100.0)
    p = {'qty': 10, 'price': 1100.0, 'avg_price': 1000.0, 'tag': 'sim4'}

    _correct_sell(led, {}, '005930', p, filled_qty=0, fill_px=0.0)

    assert abs(led['turn']['fees_realized']) < 1e-9


def test_no_turn_does_not_crash():
    """턴이 없을 때(프로그램 OFF 중 잔여 정산)도 죽지 않는다."""
    led = {'realized_pnl': 0.0}
    accrue_realized_pnl(led, {'005930': {'avg_price': 1000.0, 'quantity': 10}},
                        '005930', 10, 1100.0)
    _correct_sell(led, {}, '005930',
                  {'qty': 10, 'price': 1100.0, 'avg_price': 1000.0}, 0, 0.0)
