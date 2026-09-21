# -*- coding: utf-8 -*-
"""샌드박스 매수의 공시 필터 — 못 봤으면 통과가 아니라 보류다.

2026-09-17~18 item/news_notice가 HTTP 410이 됐다. fetch_dart_data는 410 페이지를
파싱해 행 0개를 찾고 "특이 공시 없음"을 돌려줬다 — 전환사채·유상증자 거부 필터가
조용히 꺼졌다. 예외 경로("DART 모니터링 일시 중단")도 원래부터 통과였다.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy import engine as eng  # noqa: E402


def _engine():
    # __init__은 Gemini·가상 포트폴리오를 띄운다 — 공시 조회는 그 어느 것도 안 쓴다.
    return eng.StrategyEngine.__new__(eng.StrategyEngine)


def _today():
    return datetime.datetime.now().strftime('%Y%m%d')


def test_오늘_전환사채_공시는_거부한다(monkeypatch):
    monkeypatch.setattr(eng.naver_api, 'disclosures', lambda code: [
        {'date': _today(), 'title': '성호전자(주) 전환사채권발행결정(제21회차)'}])
    got = _engine().fetch_dart_data('043260')
    assert got['reject'] is True and '전환사채' in got['reason']


def test_지난_악재_공시는_오늘_판단에_안_쓴다(monkeypatch):
    monkeypatch.setattr(eng.naver_api, 'disclosures', lambda code: [
        {'date': '20260831', 'title': '성호전자(주) 전환사채권발행결정(제21회차)'}])
    assert _engine().fetch_dart_data('043260')['reject'] is False


def test_공시가_없으면_통과(monkeypatch):
    monkeypatch.setattr(eng.naver_api, 'disclosures', lambda code: [])
    assert _engine().fetch_dart_data('005930')['reject'] is False


def test_못_봤으면_통과가_아니라_보류다(monkeypatch):
    """410 시절의 모양. '특이 공시 없음'으로 접으면 필터가 조용히 꺼진다."""
    monkeypatch.setattr(eng.naver_api, 'disclosures', lambda code: None)
    got = _engine().fetch_dart_data('005930')
    assert got['reject'] is True and '판정 불가' in got['reason']


def test_예외도_보류다(monkeypatch):
    def boom(code):
        raise RuntimeError('network')
    monkeypatch.setattr(eng.naver_api, 'disclosures', boom)
    assert _engine().fetch_dart_data('005930')['reject'] is True
