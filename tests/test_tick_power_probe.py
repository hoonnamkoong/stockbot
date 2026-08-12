"""체결강도(tick_power)가 왜 항상 0인지 다음 런이 스스로 말하게 만든다.

2026-08-08 발견: diag 4,576행(7~8월)의 `tick_power`가 **전부 0**이다(고유값 1개).
`fact_score`도 같다.

[2026-08-12] 응답 형태 판정(`tick_power_probe`)은 `KISDataProvider.get_tick_power`로
옮겨갔다(`tests/test_kis_tick_power.py`에서 검증). 여기 남는 건 "전량 결손"을 사람
경로로 올리는 `missing_field_alert`뿐이다 — 이미 있던 "체결강도 결손" 경고는
`log_error`(= print)라 GitHub Actions 로그에만 찍혔고 아무도 보지 않았다. 전량 결손은
'신호가 없는 날'이 아니라 '측정이 죽은 날'이므로 사람 경로로 올린다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.data_fetcher import missing_field_alert


# ── 사람 경로 ────────────────────────────────────────────────────────

def test_all_missing_raises_a_human_alert():
    """전량 결손 = 측정이 죽었다. 이건 '신호가 없는 날'과 구분되지 않은 채
    몇 주가 간다 — 실제로 그렇게 됐다."""
    msg = missing_field_alert('tick_power', missing=18, total=18)

    assert msg is not None
    assert 'tick_power' in msg


def test_partial_missing_stays_in_the_log():
    """일부 결손은 종목 사정(신규상장·거래정지)일 수 있다. 매번 울리면 둔감해진다."""
    assert missing_field_alert('tick_power', missing=3, total=18) is None


def test_nothing_missing_is_silent():
    assert missing_field_alert('tick_power', missing=0, total=18) is None


def test_no_candidates_is_not_an_outage():
    """후보가 0개인 사이클은 결손률 0/0이다. 0으로 나누거나 '전량 결손'으로
    읽으면 조용한 날마다 알림이 나간다."""
    assert missing_field_alert('tick_power', missing=0, total=0) is None
