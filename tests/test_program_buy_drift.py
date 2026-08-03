"""매수 판단가와 실제 체결 시점 가격이 벌어졌으면 사지 않는다.

2026-07-30 LG생활건강: 스크래퍼가 관측한 263,000원으로 진입 판단이 내려졌는데
주문은 09:26:47에 시장가로 나갔고 303,000원(+15.2%)에 체결됐다. 문제는 '비싸게
샀다'가 아니라 263,000 기준으로 계산된 모멘텀·ADX 판단을 15% 오른 가격에
집행했다는 것이다 — 그 가격에서는 애초 판단이 성립하지 않는다.

원인은 두 겹이다. (1) 매수 후보 가격이 스크래퍼 스냅샷이라 주문 시점엔 10분 이상
묵어 있을 수 있고, (2) 주문이 전부 시장가(ORD_DVSN=01)라 체결가를 호가에 맡긴다.
매도는 KIS 실시간 현재가를 쓰므로 이 가드를 걸지 않는다 — 청산은 무조건 나가야 한다.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.program_trader import check_buy_drift, BUY_DRIFT_MAX_PCT


def test_allows_when_price_barely_moved():
    ok, px, why = check_buy_drift('005930', 100_000, lambda _c: {'price': 100_500})
    assert ok is True
    assert px == 100_500
    assert why == ''


def test_blocks_when_price_ran_up_beyond_threshold():
    """LG생활건강 재현: 263,000 판단 → 303,000 현재가면 사지 않는다."""
    ok, px, why = check_buy_drift('051900', 263_000, lambda _c: {'price': 303_000})
    assert ok is False
    assert px == 303_000
    assert '괴리' in why


def test_boundary_is_inclusive():
    """정확히 임계면 통과한다(초과분만 막는다)."""
    decided = 100_000
    at_limit = decided * (1 + BUY_DRIFT_MAX_PCT / 100)
    ok, _px, _why = check_buy_drift('005930', decided, lambda _c: {'price': at_limit})
    assert ok is True


def test_allows_when_price_fell():
    """하락은 막지 않는다 — 판단가보다 싸게 사는 것은 불리하지 않다."""
    ok, _px, _why = check_buy_drift('005930', 100_000, lambda _c: {'price': 90_000})
    assert ok is True


def test_blocks_when_quote_unavailable():
    """현재가를 못 받으면 사지 않는다(fail-closed).

    매수는 건너뛰어도 원금 손실이 없고 10분 뒤 기회가 다시 온다. 괴리를 모르는 채
    시장가로 던지는 쪽이 위험하다.
    """
    ok, px, why = check_buy_drift('005930', 100_000, lambda _c: {})
    assert ok is False
    assert px is None
    assert '현재가' in why


def test_blocks_when_quote_raises():
    def boom(_c):
        raise RuntimeError('KIS timeout')
    ok, px, why = check_buy_drift('005930', 100_000, boom)
    assert ok is False
    assert px is None


def test_skips_guard_when_decided_price_missing():
    """판단가가 없으면 비교 자체가 불가능하다 — 기준 없는 가드는 걸지 않는다."""
    ok, _px, why = check_buy_drift('005930', 0, lambda _c: {'price': 100_000})
    assert ok is True
    assert why == ''
