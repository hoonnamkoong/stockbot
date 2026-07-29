"""Stage 3.6 Sim7 매수 게이트.

국면 파일을 못 읽었을 때 예전에는 bull_score를 50.0으로 폴백했다. 45 게이트를
그대로 통과해서, **조회가 실패한 날에도 지어낸 '보통 장' 점수로 강력매수 종목을
실제로 샀다.** 실패는 값이 아니다 — 모르면 그날은 사지 않는다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.orchestrator import SIM7_BULL_SCORE_MIN, sim7_should_buy  # noqa: E402

PICKS = [{'code': '005930', 'rank_and_recommendation': '강력 매수'}]


def test_unknown_bull_score_does_not_buy():
    assert sim7_should_buy(PICKS, None) is False


def test_buys_when_score_is_at_or_above_the_gate():
    assert sim7_should_buy(PICKS, SIM7_BULL_SCORE_MIN) is True
    assert sim7_should_buy(PICKS, 80.0) is True


def test_does_not_buy_below_the_gate():
    assert sim7_should_buy(PICKS, SIM7_BULL_SCORE_MIN - 0.1) is False


def test_no_strong_picks_does_not_buy():
    assert sim7_should_buy([], 90.0) is False
