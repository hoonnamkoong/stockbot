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


# ── 게이트 45.0 → 40.0 (2026-08-27) ────────────────────
# 08-27 14시 슬롯에 딥다이브 '강력 매수'가 2개 있었는데 bull_score 43.1로 미달해
# 통째로 스킵됐다. bull_score 40~45는 '약한 횡보'이고, 리포트 강력매수는 국면과
# 독립된 별도 신호다 — 같은 약세를 두 번 세는 셈이라 게이트를 40으로 내린다.
#
# 위쪽 테스트들은 SIM7_BULL_SCORE_MIN을 상징적으로 써서 값이 뭐든 통과한다.
# 실제 값이 바뀌었는지는 그날의 구체적 점수로 못 박는다.

def test_the_score_that_was_wrongly_skipped_now_buys():
    """2026-08-27 14:04 슬롯의 실측값. 예전 게이트(45.0)에서는 스킵됐다."""
    assert sim7_should_buy(PICKS, 43.1) is True


def test_weak_market_still_blocks():
    """내려도 바닥은 있다 — 확실한 약세에서는 여전히 안 산다."""
    assert sim7_should_buy(PICKS, 39.9) is False


def test_weight_at_the_new_gate_is_the_minimum():
    """심의 비중 앵커(GATE=45)는 그대로 둔다 — 게이트를 내리면서 비중까지
    올리면 두 가지를 한꺼번에 바꾸는 것이다. 40~45 구간은 최소 비중으로 클램프된다."""
    from src.strategy.simulators.sim7_report_follower import ReportFollowerSimulator
    sim = ReportFollowerSimulator()
    assert sim._calc_weight(43.1) == sim.WEIGHT_MIN
    assert sim._calc_weight(40.0) == sim.WEIGHT_MIN
    assert sim._calc_weight(100.0) == sim.WEIGHT_MAX
