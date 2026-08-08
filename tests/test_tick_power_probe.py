"""체결강도(tick_power)가 왜 항상 0인지 다음 런이 스스로 말하게 만든다.

2026-08-08 발견: diag 4,576행(7~8월)의 `tick_power`가 **전부 0**이다(고유값 1개).
`fact_score`도 같다. 배선은 끊겨 있지 않았다 — data_fetcher가 KIS inquire-price를
불러 `out['tday_rltv']`를 읽는다. 그러면 남는 가능성은 둘뿐이다.

  1. KIS 토큰 초기화가 실패해 블록 자체를 건너뛴다 (data_fetcher.py의 except 경로)
  2. `tday_rltv`가 응답에 없다 (필드명이 틀렸거나 KIS가 바꿨다)

로컬에는 KIS 자격증명이 없어 호출로 가릴 수 없다. **추측으로 고치면 틀린 쪽을
고치고 또 몇 주를 잃는다.** 그래서 진단을 먼저 심는다: 응답에 필드가 없으면
무엇이 왔는지 키 목록을 남긴다.

그리고 이미 있던 "체결강도 결손" 경고는 `log_error`(= print)라 GitHub Actions
로그에만 찍혔고 아무도 보지 않았다. 전량 결손은 '신호가 없는 날'이 아니라
'측정이 죽은 날'이므로 사람 경로로 올린다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.data_fetcher import (
    TICK_POWER_FIELD, tick_power_probe, missing_field_alert,
)


# ── 진단 ────────────────────────────────────────────────────────────

def test_no_probe_when_the_field_is_there():
    """정상일 때는 아무것도 남기지 않는다 — 종목마다 로그를 찍으면 20배가 된다."""
    assert tick_power_probe({TICK_POWER_FIELD: '112.4', 'stck_prpr': '70000'}) is None


def test_probe_names_the_missing_field_and_what_arrived():
    """어느 쪽 원인인지 가리려면 '무엇이 왔는가'가 있어야 한다."""
    msg = tick_power_probe({'stck_prpr': '70000', 'prdy_ctrt': '1.5'})

    assert msg is not None
    assert TICK_POWER_FIELD in msg
    assert 'stck_prpr' in msg and 'prdy_ctrt' in msg


def test_empty_response_is_also_probed():
    """빈 응답은 '필드가 없다'와 다른 원인(권한·유량제한)이지만 둘 다 남겨야 한다."""
    assert tick_power_probe({}) is not None


def test_field_value_of_zero_counts_as_missing():
    """KIS가 '0'을 돌려주면 체결강도가 0이라는 뜻이 아니라 미집계다.
    0을 유효값으로 읽으면 diag가 지금과 똑같이 전부 0인 채로 정상처럼 보인다."""
    assert tick_power_probe({TICK_POWER_FIELD: '0'}) is not None


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
