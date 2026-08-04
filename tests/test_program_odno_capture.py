"""E10 (2026-08-04 스크래퍼 지연 재설계): 주문 응답에서 KIS 주문번호(odno)를 꺼낸다.

/api/trade/order가 이미 응답에 data.odno를 실어 보내는데(order/route.ts) 파이썬이
버리고 있었다. 이번 배포는 '기록'까지만 한다 — 원장의 avg_price·realized_pnl을
이 값으로 정정하는 자동 대사는 다음 단계(설계 문서 Rollback Plan)다.

'UNKNOWN'은 라우트가 ODNO를 못 받았을 때 채우는 폴백값이라 매칭에 못 쓴다 —
빈 문자열로 취급해야 한다(추정 매칭은 틀릴 수 있고, 틀린 손익은 없는 손익보다 나쁘다).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.program_trader import _extract_odno


def test_extracts_odno_from_successful_response():
    res = {'success': True, 'data': {'odno': '0000123456', 'rt_cd': '0', 'msg': 'ok'}}
    assert _extract_odno(res) == '0000123456'


def test_unknown_odno_treated_as_absent():
    res = {'success': True, 'data': {'odno': 'UNKNOWN', 'rt_cd': '0', 'msg': 'ok'}}
    assert _extract_odno(res) == ''


def test_missing_data_key_returns_empty():
    assert _extract_odno({'success': True}) == ''


def test_missing_odno_key_returns_empty():
    assert _extract_odno({'success': True, 'data': {'rt_cd': '0'}}) == ''


def test_none_response_returns_empty():
    assert _extract_odno(None) == ''


def test_strips_whitespace():
    res = {'success': True, 'data': {'odno': '  0000999999  '}}
    assert _extract_odno(res) == '0000999999'
