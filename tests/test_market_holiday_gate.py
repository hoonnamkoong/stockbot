"""휴장일 게이트 회귀 테스트.

2026-07-17(공휴일)에 스크래퍼가 돌고 텔레그램이 나간 사고의 재발을 막는다.
원인: chk-holiday 응답에 없는 필드(bzdy_tp_cd)를 읽어 opnd_yn을 놓쳤고,
holidays 0.86이 2026-07-17을 몰랐으며, 판정 실패가 조용히 개장으로 통과했다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime

import pytest

import src.market_calendar as mc
from src.pipeline.context import PipelineContext


def ctx_at(when: datetime) -> PipelineContext:
    ctx = object.__new__(PipelineContext)
    ctx.now_kst = when
    ctx.today_str = when.strftime('%Y%m%d')
    ctx.today_display = when.strftime('%Y.%m.%d')
    return ctx


@pytest.fixture(autouse=True)
def _no_force_run(monkeypatch):
    """FORCE_RUN이 셸에 남아 있으면 게이트 테스트가 전부 무의미해진다."""
    monkeypatch.delenv('FORCE_RUN', raising=False)


# ── 달력 기반 판정 ──

def test_holiday_20260717_is_closed(monkeypatch):
    """2026-07-17(금)은 휴장이다 — 이 사고의 회귀 테스트.

    평일이라 주말 조기 반환에 걸리지 않는다. 달력 경로가 실제로 판정한다.
    """
    monkeypatch.setattr(mc, 'load_calendar', lambda *a, **k: {'20260717': 'N'})
    assert ctx_at(datetime(2026, 7, 17, 10, 0)).is_trading_day() is False


def test_open_day_from_calendar(monkeypatch):
    """2026-07-20(월) 개장."""
    monkeypatch.setattr(mc, 'load_calendar', lambda *a, **k: {'20260720': 'Y'})
    assert ctx_at(datetime(2026, 7, 20, 10, 0)).is_trading_day() is True


def test_weekend_is_closed_without_api(monkeypatch):
    """주말(2026-07-18 토)은 API·달력을 건드리지 않고 즉시 휴장."""
    def _boom(*a, **k):
        raise AssertionError("주말엔 달력을 읽지 않아야 한다")
    monkeypatch.setattr(mc, 'load_calendar', _boom)
    assert ctx_at(datetime(2026, 7, 18, 10, 0)).is_trading_day() is False


# ── 재조회 계층 ──

def test_refetches_when_today_missing(monkeypatch):
    """달력에 오늘이 없으면 직접 조회한다."""
    monkeypatch.setattr(mc, 'load_calendar', lambda *a, **k: {'20260101': 'N'})
    monkeypatch.setattr(mc, 'refresh_calendar', lambda base: {'20260720': 'Y'})
    assert ctx_at(datetime(2026, 7, 20, 10, 0)).is_trading_day() is True


def test_refetch_failure_is_none(monkeypatch):
    """재조회가 실패하면 판정 불가(None)다. True가 아니다."""
    monkeypatch.setattr(mc, 'load_calendar', lambda *a, **k: {})

    def _fail(base):
        raise RuntimeError("KIS 장애")
    monkeypatch.setattr(mc, 'refresh_calendar', _fail)

    assert ctx_at(datetime(2026, 7, 20, 10, 0)).is_trading_day() is None


def test_refetch_without_today_is_none(monkeypatch):
    """재조회는 성공했는데 응답에 오늘이 없으면 판정 불가."""
    monkeypatch.setattr(mc, 'load_calendar', lambda *a, **k: {})
    monkeypatch.setattr(mc, 'refresh_calendar', lambda base: {'20260721': 'Y'})
    assert ctx_at(datetime(2026, 7, 20, 10, 0)).is_trading_day() is None


# ── FORCE_RUN 탈출구 ──

def test_force_run_bypasses_gate(monkeypatch):
    """KIS 장애 시 수동 실행 수단. 휴장 판정도 우회한다."""
    monkeypatch.setenv('FORCE_RUN', 'true')
    monkeypatch.setattr(mc, 'load_calendar', lambda *a, **k: {'20260717': 'N'})
    assert ctx_at(datetime(2026, 7, 17, 10, 0)).is_trading_day() is True


def test_force_run_false_does_not_bypass(monkeypatch):
    """workflow_dispatch 기본값이 'false' 문자열로 넘어온다."""
    monkeypatch.setenv('FORCE_RUN', 'false')
    monkeypatch.setattr(mc, 'load_calendar', lambda *a, **k: {'20260717': 'N'})
    assert ctx_at(datetime(2026, 7, 17, 10, 0)).is_trading_day() is False


def test_force_run_empty_does_not_bypass(monkeypatch):
    """repository_dispatch에선 inputs가 없어 빈 문자열이 넘어온다."""
    monkeypatch.setenv('FORCE_RUN', '')
    monkeypatch.setattr(mc, 'load_calendar', lambda *a, **k: {'20260717': 'N'})
    assert ctx_at(datetime(2026, 7, 17, 10, 0)).is_trading_day() is False


# ── 실거래 게이트는 판정 불가 시 닫힌다 ──

def test_market_hours_closed_when_undetermined(monkeypatch):
    """판정 불가면 매수 게이트는 닫힌다. None이 아니라 False를 반환해야 한다."""
    monkeypatch.setattr(PipelineContext, 'is_trading_day', lambda self: None)
    assert ctx_at(datetime(2026, 7, 20, 10, 0)).is_market_hours() is False


def test_after_close_closed_when_undetermined(monkeypatch):
    monkeypatch.setattr(PipelineContext, 'is_trading_day', lambda self: None)
    assert ctx_at(datetime(2026, 7, 20, 16, 0)).is_after_market_close() is False


def test_holidays_package_not_imported():
    """holidays 패키지 폴백은 제거됐다 — 신규 지정 공휴일을 못 잡는다.

    import 문만 본다. 왜 안 쓰는지 설명하는 주석·docstring은 남겨둬야 하므로
    소스 전체에서 'holidays' 문자열을 찾으면 그 설명에 자기 자신이 걸린다.
    """
    import inspect
    from src.pipeline import context
    source = inspect.getsource(context)
    assert 'import holidays' not in source
    assert 'from holidays' not in source
