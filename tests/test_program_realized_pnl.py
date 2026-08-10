"""원장의 realized_pnl 누적에 거래 비용이 들어가야 한다.

2026-08-10 09:44 대덕전자(353200) 1주 매도에서 원장은 -3,500원을 적었고 KIS
실측은 -3,723원이었다. 223원이 위탁수수료와 증권거래세다.

realized_pnl은 화면 표시용이 아니라 **effective_budget(복리)의 근거**다
(program_trader.py의 `budget + realized_pnl`). 그래서 이 편향은 수익률만
좋아 보이게 하는 데서 끝나지 않고 다음 매수의 주문 크기까지 부풀린다.

요율 자체의 검증은 tests/test_trade_fees.py가 한다. 여기서는 그 계산이 원장에
실제로 반영되는지만 본다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.program_trader import accrue_realized_pnl

# 2026-08-10 대덕전자 실거래 (KIS 체결 실측가)
KIS_BUY_FILL = 111_500
KIS_SELL_FILL = 108_000
KIS_REALIZED = -3_723


def test_accrued_delta_matches_kis_measurement():
    """실거래 한 건을 원장에 반영하면 KIS 실측에 붙어야 한다."""
    ledger = {'realized_pnl': 0}
    positions = {'353200': {'quantity': 1, 'avg_price': KIS_BUY_FILL}}

    accrue_realized_pnl(ledger, positions, '353200', qty=1, price=KIS_SELL_FILL)

    assert abs(ledger['realized_pnl'] - KIS_REALIZED) < 10, (
        f"KIS 실측 {KIS_REALIZED:,}원 대비 {abs(ledger['realized_pnl'] - KIS_REALIZED):,.2f}원 차이"
    )


def test_accrues_onto_existing_balance():
    """기존 누적에 더한다 — 덮어쓰면 그날 이전 손익이 통째로 사라진다."""
    ledger = {'realized_pnl': 19_595}
    positions = {'353200': {'quantity': 1, 'avg_price': KIS_BUY_FILL}}

    accrue_realized_pnl(ledger, positions, '353200', qty=1, price=KIS_SELL_FILL)

    assert abs(ledger['realized_pnl'] - (19_595 + KIS_REALIZED)) < 10


def test_missing_realized_pnl_key_starts_from_zero():
    """원장에 키가 없어도 0에서 시작한다(옛 원장 호환)."""
    ledger = {}
    positions = {'005930': {'quantity': 10, 'avg_price': 60_000}}

    accrue_realized_pnl(ledger, positions, '005930', qty=10, price=61_000)

    assert ledger['realized_pnl'] > 0


def test_ignores_code_absent_from_positions():
    """원장에 없는 종목은 기준가가 없다 — 손익을 지어내지 않는다."""
    ledger = {'realized_pnl': 500}
    positions = {}

    accrue_realized_pnl(ledger, positions, '353200', qty=1, price=KIS_SELL_FILL)

    assert ledger['realized_pnl'] == 500


def test_partial_sell_accrues_only_sold_quantity():
    """10주 중 3주만 팔면 3주분만 계상한다."""
    ledger = {'realized_pnl': 0}
    positions = {'005930': {'quantity': 10, 'avg_price': 60_000}}

    accrue_realized_pnl(ledger, positions, '005930', qty=3, price=61_000)

    assert 0 < ledger['realized_pnl'] < 3_000


def test_cost_is_charged_on_a_winning_trade():
    """이익 거래도 비용을 낸다 — 단순 차액(+10,000)보다 작아야 한다."""
    ledger = {'realized_pnl': 0}
    positions = {'005930': {'quantity': 1, 'avg_price': 100_000}}

    accrue_realized_pnl(ledger, positions, '005930', qty=1, price=110_000)

    assert ledger['realized_pnl'] < 10_000
