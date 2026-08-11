"""딥다이브 리포트에 "향후 전망" 섹션이 추가됐다 — 근거 유지/약화 시나리오이지
확정 예측이 아니다. 프롬프트가 숫자를 지어내지 말라고 명시하는지, 응답이
비어도 조용히 넘어가는지(신뢰할 수 없는 텍스트를 지어내지 않는지) 검증한다.

Design: ~/.gstack/projects/hoonnamkoong-stockbot/Hoon_DT-main-design-20260811-222707.md
"""
import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.advisor import StrategyAdvisor


def _advisor():
    a = object.__new__(StrategyAdvisor)
    a.gemini = mock.MagicMock()
    return a


def _fake_response(payload: dict):
    r = mock.MagicMock()
    r.text = json.dumps(payload, ensure_ascii=False)
    return r


def _stock(code='005930', **extra):
    base = {'code': code, 'name': '삼성전자', 'price': 70000, 'rank': 1,
            'foreign_change': 0.5}
    base.update(extra)
    return base


def test_prompt_forbids_fabricating_numbers():
    """프롬프트 자체가 목표가·수익률을 지어내지 말라고 명시해야 한다."""
    a = _advisor()
    a.gemini._call_gemini_safe.return_value = _fake_response({
        'rank_and_recommendation': '매수', 'business_bullets': [],
        'rationale_bullets': [], 'outlook_bullets': [], 'risk_bullets': [],
    })

    a.generate_deep_dive_report([_stock()])

    prompt = a.gemini._call_gemini_safe.call_args[0][0]
    assert '지어내지' in prompt
    assert 'outlook_bullets' in prompt


def test_outlook_bullets_render_as_section_3():
    a = _advisor()
    a.gemini._call_gemini_safe.return_value = _fake_response({
        'rank_and_recommendation': '매수', 'business_bullets': ['반도체'],
        'rationale_bullets': ['수급 개선'],
        'outlook_bullets': ['외인 매수 지속 시 상승 흐름 유지', '수급 약화 시 조정 가능'],
        'risk_bullets': ['업황 둔화'],
    })

    report = a.generate_deep_dive_report([_stock()])

    assert '3. 향후 전망 (AI 추정)' in report
    assert '외인 매수 지속 시 상승 흐름 유지' in report
    assert '수급 약화 시 조정 가능' in report


def test_missing_outlook_shows_insufficient_basis_not_fabricated_text():
    """모델이 outlook_bullets를 안 주면 지어내지 않고 '판단 근거 부족'이라고만 쓴다."""
    a = _advisor()
    a.gemini._call_gemini_safe.return_value = _fake_response({
        'rank_and_recommendation': '매수', 'business_bullets': [],
        'rationale_bullets': [], 'risk_bullets': [],
        # outlook_bullets 자체가 없음
    })

    report = a.generate_deep_dive_report([_stock()])

    assert '3. 향후 전망 (AI 추정)' in report
    assert '판단 근거 부족' in report


def test_up_to_five_candidates_are_processed():
    """final_candidates가 5개 이상 와도 최대 5개까지 처리해야 한다(기존 2개 하드캡 제거)."""
    a = _advisor()
    a.gemini._call_gemini_safe.return_value = _fake_response({
        'rank_and_recommendation': '매수', 'business_bullets': [],
        'rationale_bullets': [], 'outlook_bullets': [], 'risk_bullets': [],
    })
    stocks = [_stock(code=str(i), name=f'종목{i}') for i in range(7)]

    a.generate_deep_dive_report(stocks)

    assert a.gemini._call_gemini_safe.call_count == 5
