"""실전 매매 준비상태 — 주문을 내지 않고 "쏠 수 있는 상태인가"만 본다.

2026-09-01 장중 실전 0건의 원인을 찾는 데 오래 걸린 이유는, **"안 살 이유가
있었다"와 "살 수 없는 상태였다"가 밖에서 똑같이 생겼기** 때문이다. 전자는
전략 문제고 후자는 사고인데 둘 다 "0건"으로만 보였다.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.readiness import evaluate  # noqa: E402


def test_all_green_is_ready():
    ok, msg = evaluate({
        'KIS 토큰': (True, '유효'),
        '계좌 조회': (True, '예수금 1,000,000원'),
        '실전 심 유니버스': (True, '30종목'),
    })
    assert ok is True
    assert '준비 완료' in msg


def test_any_failure_blocks():
    ok, msg = evaluate({
        'KIS 토큰': (True, '유효'),
        '계좌 조회': (False, '계좌 번호가 설정되지 않았습니다.'),
        '실전 심 유니버스': (True, '30종목'),
    })
    assert ok is False
    assert '준비 실패' in msg
    assert '계좌 번호가 설정되지 않았습니다.' in msg
    # 통과한 항목도 함께 보여야 어디까지 살아 있는지 안다
    assert '✅ KIS 토큰' in msg


def test_unknown_counts_as_failure():
    """확인하지 못한 것을 통과로 치면 이 점검이 '항상 초록'이 되어 없느니만 못하다."""
    ok, msg = evaluate({
        'KIS 토큰': (True, '유효'),
        '실전 심 유니버스': (None, '조회 실패(유니버스를 못 받았다)'),
    })
    assert ok is False
    assert '❓ 실전 심 유니버스' in msg


def test_empty_universe_is_not_ready():
    """유니버스가 0종목이면 살 수 없는 상태다 — '조건 미달'이 아니다."""
    ok, _ = evaluate({'실전 심 유니버스': (False, '0종목')})
    assert ok is False


def test_message_names_what_a_zero_day_would_mean():
    """이 점검의 값어치는 그날 0건을 해석해주는 데 있다. 문구가 그걸 말해야 한다."""
    _, msg = evaluate({'계좌 조회': (False, 'X')})
    assert '전략이 아니라 배선' in msg
