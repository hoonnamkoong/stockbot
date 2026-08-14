"""거래 비용(위탁수수료·증권거래세) — 심과 실전이 공유하는 단일 정의.

================================================================
왜 한 곳에 있어야 하는가
================================================================
2026-08-10까지 비용 모델이 **한쪽에만** 있었다. base_simulator는 매수 시
`cash -= cost + fee`, 매도 시 `cash += gross - fee - tax`로 비용을 다 뗐는데,
프로그램 매매 원장의 `realized_delta = qty * (price - avg_price)`에는 비용 항이
아예 없었다. 같은 전략이 심에서는 수수료를 내고 실전에서는 안 내는 상태였고,
그건 [[program-trading-parity-mandate]]가 금지하는 종류의 어긋남이다.

실측(2026-08-10 대덕전자 1주): 원장 -3,500원 vs KIS 실측 -3,723원. 차이 223원.
매도할 때마다 원장이 실제보다 좋게 나오는 **단방향 편향**이고, realized_pnl은
effective_budget(복리)의 근거라 예산까지 함께 부풀린다.

그래서 상수를 복사하지 않는다. 복사가 곧 이 버그의 형태였다.

================================================================
정밀도에 대해
================================================================
KIS는 원 단위로 절사하고 증권사·유관기관 수수료가 계좌마다 다르다. 여기 값은
근사이며 실측 오차는 위 거래에서 4.32원(0.12%)이었다. **정확한 값이 필요하면
KIS 실현손익 조회(TTTC8715R)를 쓴다** — 이 모듈은 주문 시점에 그 조회 없이
원장을 갱신하기 위한 추정치다.
"""

# 2026-08-10 실거래로 검증한 요율. 오래 전부터 심이 쓰던 값이고, 바꾸면
# tests/test_trade_fees.py의 실측 재현 테스트가 먼저 깨진다.
BUY_FEE_RATE = 0.00015    # 매수 위탁수수료율
SELL_FEE_RATE = 0.00015   # 매도 위탁수수료율
SELL_TAX_RATE = 0.0018    # 증권거래세율 (매도에만 부과)


def buy_cost(qty: int, price: float) -> float:
    """매수에 드는 비용(수수료). 거래세는 매도에만 붙는다."""
    return qty * price * BUY_FEE_RATE


def sell_cost(qty: int, price: float) -> float:
    """매도에 드는 비용(수수료 + 증권거래세)."""
    return qty * price * (SELL_FEE_RATE + SELL_TAX_RATE)


def roundtrip_cost(qty: int, buy_price: float, sell_price: float) -> float:
    """`realized_pnl_after_fees`가 빼는 비용과 **정확히 같은 값**.

    손익에서 뺀 금액을 화면이 "수수료 N원 차감"으로 보여주려면 그 값을 따로
    낼 수 있어야 한다. 두 함수가 갈리면 화면의 검산(gross - 수수료 = net)이
    깨지므로, 항이 바뀌면 반드시 함께 바꾼다.
    """
    return buy_cost(qty, buy_price) + sell_cost(qty, sell_price)


def realized_pnl_after_fees(qty: int, buy_price: float, sell_price: float) -> float:
    """매도 체결분의 실현손익 — 왕복 비용을 뺀 값.

    `buy_price`는 매입 평단(원장의 avg_price)이다. 매도하는 수량에 해당하는
    **매수 수수료도 함께** 뺀다 — 심의 cash 순증과 같은 의미가 되게 하기 위한
    것이고, 매도 비용만 빼면 매수 쪽 비용이 영원히 어디에도 계상되지 않는다.
    """
    gross = qty * (sell_price - buy_price)
    return gross - buy_cost(qty, buy_price) - sell_cost(qty, sell_price)
