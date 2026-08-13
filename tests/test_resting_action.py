"""미체결 매수를 유지할지, 거둘지, 시장가로 올릴지.

2026-08-13 사용자 보고: 한투 앱 이력에 주문취소가 어마어마하게 많다.

원인은 `_keep_resting`의 조건이 `int(live) != int(지정가)` 하나뿐이었다는 것이다.
현재가가 지정가와 **정확히 같을 때만** 유지하고 나머지는 전부 취소한다. 이건
상한가처럼 현재가가 얼어붙은 경우(001210)만 살리려고 만든 조건인데, 그 결과
주가가 1원만 움직여도 2분마다 취소→재주문이 돈다. 정규장 6.5시간이면 미체결
주문 하나당 하루 최대 195번이다.

가격-시간 우선이라 재주문은 그 가격대 대기열 **맨 뒤**로 간다. 2분마다 순번을
스스로 리셋하니 체결이 구조적으로 어렵다.

특히 나빴던 것: **유리하게 움직인 경우와 불리하게 움직인 경우를 구분하지
않았다.** 매수 지정가 5,300에 현재가가 5,250으로 내려온 건 체결 직전인데,
그걸 취소하고 5,250에 다시 주문하면 앞줄을 버리고 맨 뒤로 간다.
`check_buy_drift`는 "상승 괴리만 막는다. 판단가보다 싸진 것은 불리하지 않다"고
명시하는데, 이쪽에는 그 대칭이 없었다.

여기서 정하는 규칙 셋:
  1. 현재가가 지정가 **이하**면 유지한다(체결 대기 중이거나 임박한 상태다).
  2. 주문 직후 RESTING_MIN_MIN 동안은 가격이 올라가도 유지한다 — 2분마다
     재평가하면 어떤 주문도 대기열에서 살아남지 못한다.
  3. MARKET_ESCALATE_MIN을 넘도록 안 붙으면 시장가로 올린다. 그 자리는
     대기열이 두꺼운 것이고, 계속 지정가로 재주문해봐야 예산만 묶인다.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.workers.program_trader import (
    MARKET_ESCALATE_MIN, RESTING_MIN_MIN, resting_action,
)

ORDERED = datetime(2026, 8, 13, 10, 0, 0)
LIMIT = 5300.0


def _entry(side='buy', price=LIMIT, ordered_at=ORDERED.isoformat()):
    return {'odno': 'OD1', 'side': side, 'qty': 34, 'price': price,
            'ordered_at': ordered_at}


def _at(minutes):
    return datetime(2026, 8, 13, 10, 0, 0).replace(
        minute=(minutes % 60), hour=10 + minutes // 60)


# ── 1. 유리하게 움직였으면 유지한다 ──────────────────────────────────

def test_price_below_the_limit_keeps_resting():
    """체결 직전인 주문을 취소하면 앞줄을 버리고 맨 뒤로 간다."""
    assert resting_action(_entry(), live=5250, now_kst=_at(10)) == 'keep'


def test_price_equal_to_the_limit_keeps_resting():
    """상한가 고착(001210)이 이 경우다. PR #28이 살린 케이스를 깨지 않는다."""
    assert resting_action(_entry(), live=5300, now_kst=_at(10)) == 'keep'


def test_price_above_the_limit_is_reordered():
    """시장이 내 지정가 위로 갔다 = 이 가격엔 안 붙는다. 쫓아가야 한다."""
    assert resting_action(_entry(), live=5350, now_kst=_at(10)) == 'reorder'


# ── 2. 최소 유지 시간 ────────────────────────────────────────────────

def test_a_fresh_order_is_kept_even_if_the_price_ran_up():
    """2분마다 재평가하면 어떤 주문도 대기열에서 살아남지 못한다."""
    assert RESTING_MIN_MIN >= 4, '태스커 2분 주기보다 확실히 커야 뜻이 있다'
    assert resting_action(_entry(), live=9999, now_kst=_at(RESTING_MIN_MIN - 1)) == 'keep'


def test_after_the_minimum_a_run_up_is_chased():
    assert resting_action(_entry(), live=9999, now_kst=_at(RESTING_MIN_MIN + 1)) == 'reorder'


# ── 3. 오래 안 붙으면 시장가 ─────────────────────────────────────────

def test_long_unfilled_escalates_to_market():
    assert resting_action(_entry(), live=5250,
                          now_kst=_at(MARKET_ESCALATE_MIN + 1)) == 'escalate'


def test_escalation_wins_over_keep():
    """지정가 이하인데도 15분을 못 붙었다 = 대기열이 두껍다. 계속 기다려봐야
    예산만 묶인다."""
    assert resting_action(_entry(), live=LIMIT,
                          now_kst=_at(MARKET_ESCALATE_MIN + 5)) == 'escalate'


def test_not_yet_escalated_before_the_threshold():
    assert resting_action(_entry(), live=5250,
                          now_kst=_at(MARKET_ESCALATE_MIN - 1)) == 'keep'


# ── 모르는 것은 기존 동작(거둔다)으로 ────────────────────────────────

def test_missing_quote_falls_back_to_reorder():
    """시세를 모르는 채 주문을 시장에 남겨두지 않는다(기존 동작 유지)."""
    for bad in (None, 0, -1):
        assert resting_action(_entry(), live=bad, now_kst=_at(10)) == 'reorder'


def test_unparsable_ordered_at_still_uses_the_price_rule():
    """시각을 못 읽어도 가격 비교는 할 수 있다. 그걸 포기하면 취소 루프로 돌아간다."""
    e = _entry(ordered_at='(없음)')
    assert resting_action(e, live=5250, now_kst=_at(10)) == 'keep'
    assert resting_action(e, live=5350, now_kst=_at(10)) == 'reorder'


def test_sell_is_never_kept():
    """매도는 시장가라 이 경로에 오지 않는다. 와도 붙들지 않는다 — 청산은
    무조건 나가야 한다."""
    assert resting_action(_entry(side='sell'), live=5250, now_kst=_at(10)) == 'reorder'


def test_zero_limit_price_is_reordered():
    assert resting_action(_entry(price=0), live=5250, now_kst=_at(10)) == 'reorder'
