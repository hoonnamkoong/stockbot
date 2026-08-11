"""algo_04_v2.py의 BUY 판정에서 죽은 sentiment 게이트를 제거했다.

과거 `cond2 = sentiment == 'Positive'`는 실제 저장 형식('2', '-3' 같은 숫자
문자열)과 절대 일치하지 않아 BUY 분기가 도달 불가능했다. 제거 후 나머지
AND 조건(게시글수·외인수급·등락률)만 충족하면 BUY가 실제로 나가야 한다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.monthly.algo_04_v2 import Algo04V2


def _strategy():
    return Algo04V2()


def _passing_stock(**overrides):
    base = {'change_rate': '10.0%', 'recent_posts_count': 150,
            'foreign_change': 1.0, 'price': 10000}
    base.update(overrides)
    return base


APPROVED = {"decision": "APPROVED", "telegram_narrative": "테스트 승인"}
NO_REJECT = {"reject": False, "reason": "특이 공시 없음"}


def test_buy_is_reachable_when_and_filter_passes_regardless_of_sentiment():
    """[회귀 방지] sentiment 값과 무관하게 나머지 조건만 맞으면 BUY가 나가야 한다."""
    stock = _passing_stock(sentiment='2')  # 실제 운영에서 저장되는 숫자 문자열

    result = _strategy().analyze_target(stock, NO_REJECT, APPROVED, current_cash=1_000_000)

    assert result['action'] == 'BUY'


def test_buy_is_reachable_with_no_sentiment_field_at_all():
    """sentiment 키가 아예 없어도(예: 초기 StockData) BUY가 막히면 안 된다."""
    stock = _passing_stock()
    assert 'sentiment' not in stock

    result = _strategy().analyze_target(stock, NO_REJECT, APPROVED, current_cash=1_000_000)

    assert result['action'] == 'BUY'


def test_buy_is_reachable_even_when_sentiment_is_unmeasured_marker():
    """폴백 경로가 남기는 '측정 불가' 문자열도 게이트에 영향을 주면 안 된다
    (게이트 자체가 없어졌으니 당연하지만, 회귀 방지로 명시)."""
    stock = _passing_stock(sentiment='측정 불가')

    result = _strategy().analyze_target(stock, NO_REJECT, APPROVED, current_cash=1_000_000)

    assert result['action'] == 'BUY'


def test_watch_when_post_count_filter_fails():
    stock = _passing_stock(recent_posts_count=10)

    result = _strategy().analyze_target(stock, NO_REJECT, APPROVED, current_cash=1_000_000)

    assert result['action'] == 'WATCH'
    assert result['reason'] == '1차 필터(AND) 조건 미충족'


def test_watch_when_foreign_flow_is_negative():
    stock = _passing_stock(foreign_change=-0.5)

    result = _strategy().analyze_target(stock, NO_REJECT, APPROVED, current_cash=1_000_000)

    assert result['action'] == 'WATCH'


def test_watch_when_change_rate_out_of_band():
    stock = _passing_stock(change_rate='25.0%')

    result = _strategy().analyze_target(stock, NO_REJECT, APPROVED, current_cash=1_000_000)

    assert result['action'] == 'WATCH'


def test_dart_reject_still_blocks_after_and_filter_passes():
    """1차 필터를 통과해도 DART 거부는 여전히 막아야 한다 — 2차 검증 오버레이는 안 건드림."""
    stock = _passing_stock()

    result = _strategy().analyze_target(
        stock, {"reject": True, "reason": "유상증자 공시"}, APPROVED, current_cash=1_000_000)

    assert result['action'] == 'WATCH'
    assert 'DART 거부됨' in result['reason']


def test_llm_rejection_still_blocks_after_and_filter_passes():
    stock = _passing_stock()

    result = _strategy().analyze_target(
        stock, NO_REJECT, {"decision": "REJECTED"}, current_cash=1_000_000)

    assert result['action'] == 'WATCH'
    assert result['reason'] == 'AI 모멘텀 승인 거부'
