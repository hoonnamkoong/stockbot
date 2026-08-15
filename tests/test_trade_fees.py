"""프로그램 매매 원장의 실현손익에서 수수료·제세금이 통째로 빠져 있었다.

2026-08-10 09:44, 대덕전자(353200) 1주를 팔았다.
  - 원장 realized_pnl 변화: +19,595 → +16,095 = **-3,500원**
  - KIS 실측(TTTC8715R):                        **-3,723원**
  - 차이 223원 = 위탁수수료 + 증권거래세

program_trader.py의 `realized_delta = qty * (price - avg_price)`에는 비용 항이
없다. 매도할 때마다 원장이 실제보다 좋게 나오는 **단방향 편향**이라 매매 횟수에
비례해 벌어지고, realized_pnl은 effective_budget(복리)의 근거이므로 예산까지
부풀린다.

더 중요한 건 이게 파리티 위반이라는 점이다 — base_simulator는 매수 시
`cash -= cost + fee`, 매도 시 `cash += gross - fee - tax`로 비용을 다 뗀다.
같은 전략이 심에서는 수수료를 내고 실전에서는 안 내는 상태였다.

요율은 지어낸 값이 아니라 프로젝트가 이미 쓰던 상수이고, 위 실거래로 검증했다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.trade.fees import realized_pnl_after_fees

# 2026-08-10 대덕전자 실거래 (KIS 체결 실측)
DAEDUK = dict(qty=1, buy_price=111_500, sell_price=108_000)
DAEDUK_KIS_ACTUAL = -3_723


def test_reproduces_measured_kis_realized_pnl():
    """실거래 한 건의 KIS 실측 실현손익을 재현해야 한다.

    이 테스트가 이 모듈의 존재 이유다. 요율을 바꾸면 여기가 먼저 깨진다.
    허용 오차 10원은 KIS의 원 단위 절사분이다(실측 오차 4.32원).
    """
    net = realized_pnl_after_fees(**DAEDUK)

    assert abs(net - DAEDUK_KIS_ACTUAL) < 10, (
        f"KIS 실측 {DAEDUK_KIS_ACTUAL:,}원과 {abs(net - DAEDUK_KIS_ACTUAL):,.2f}원 차이"
    )


def test_costs_make_result_worse_than_naive_difference():
    """비용이 실제로 빠져야 한다 — 기존 식(단순 차액)보다 반드시 나쁘다."""
    naive = (DAEDUK['sell_price'] - DAEDUK['buy_price']) * DAEDUK['qty']

    net = realized_pnl_after_fees(**DAEDUK)

    assert net < naive, '비용이 반영되지 않았다'


def test_charges_cost_even_on_a_winning_trade():
    """이익 거래에서도 비용은 나간다 — 손실 거래에만 붙이면 수익률이 부풀려진다."""
    net = realized_pnl_after_fees(qty=1, buy_price=100_000, sell_price=110_000)

    assert net < 10_000


def test_scales_with_quantity():
    """수량이 늘면 비용도 비례한다 — 1주 비용을 전체에 쓰면 대량 매도에서 크게 틀린다."""
    one = realized_pnl_after_fees(qty=1, buy_price=100_000, sell_price=110_000)
    ten = realized_pnl_after_fees(qty=10, buy_price=100_000, sell_price=110_000)

    assert abs(ten - one * 10) < 0.01


def test_simulator_and_live_ledger_share_one_rate_table():
    """심과 실전이 같은 요율을 써야 한다 — 갈리는 순간 파리티가 깨진다.

    이 버그의 형태가 정확히 '한쪽에만 있는 비용 모델'이었다. 심은 매수·매도에서
    수수료를 떼는데 실전 원장은 안 뗐다. 값이 아니라 **출처**가 하나여야 한다.
    """
    from src.strategy.simulators.base_simulator import BaseSimulator
    from src.trade import fees

    assert BaseSimulator.BUY_FEE_RATE == fees.BUY_FEE_RATE
    assert BaseSimulator.SELL_FEE_RATE == fees.SELL_FEE_RATE
    assert BaseSimulator.SELL_TAX_RATE == fees.SELL_TAX_RATE


def test_flat_trade_loses_exactly_the_cost():
    """같은 가격에 사고팔면 손익은 0이 아니라 비용만큼 마이너스다."""
    net = realized_pnl_after_fees(qty=1, buy_price=100_000, sell_price=100_000)

    assert net < 0
    # 매수수수료 15 + 매도수수료 15 + 거래세 180 = 210원
    assert abs(net - (-210)) < 0.01


from src.trade.fees import roundtrip_cost, buy_cost, sell_cost


def test_roundtrip_cost_is_buy_plus_sell():
    """왕복 비용 = 매수 수수료 + (매도 수수료 + 거래세)."""
    got = roundtrip_cost(10, 1000.0, 1100.0)
    assert got == buy_cost(10, 1000.0) + sell_cost(10, 1100.0)


def test_roundtrip_cost_is_what_realized_pnl_subtracted():
    """손익에서 뺀 비용과 정확히 같은 값이어야 한다 — 다르면 화면 검산이 깨진다."""
    from src.trade.fees import realized_pnl_after_fees
    gross = 10 * (1100.0 - 1000.0)
    net = realized_pnl_after_fees(10, 1000.0, 1100.0)
    assert abs((gross - net) - roundtrip_cost(10, 1000.0, 1100.0)) < 1e-9


def test_roundtrip_cost_zero_qty_is_zero():
    assert roundtrip_cost(0, 1000.0, 1100.0) == 0.0
