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
from src.pipeline.context import PipelineContext, CYCLE_SECONDS


def ctx_at(when: datetime) -> PipelineContext:
    ctx = object.__new__(PipelineContext)
    ctx.now_kst = when
    ctx.today_str = when.strftime('%Y%m%d')
    ctx.today_display = when.strftime('%Y.%m.%d')
    # __init__을 건너뛰므로 직접 채운다. 진단 로그의 조인 키라 없으면
    # run_pipeline이 AttributeError로 죽는다.
    ctx.cycle_id = int(when.timestamp()) // CYCLE_SECONDS
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


# ── 오케스트레이터 게이트 ──

def _stub_workers(monkeypatch):
    """Stage 1이 돌면 테스트가 네트워크를 탄다. 돌면 즉시 실패시킨다."""
    from src.pipeline import orchestrator

    def _boom(*a, **k):
        raise AssertionError("게이트가 열려 파이프라인이 진행됐다")

    monkeypatch.setattr(orchestrator, 'DataFetcherWorker', _boom)
    monkeypatch.setattr(orchestrator, 'StorageManager', lambda *a, **k: None)


def test_pipeline_stops_and_warns_when_undetermined(monkeypatch):
    """판정 불가면 중단하고 경고를 보낸다."""
    from src.pipeline import orchestrator

    _stub_workers(monkeypatch)
    sent = []
    monkeypatch.setattr(orchestrator, '_notify_holiday_check_failed',
                        lambda ctx: sent.append(ctx.today_str))
    monkeypatch.setattr(PipelineContext, 'is_trading_day', lambda self: None)

    ctx = ctx_at(datetime(2026, 7, 20, 10, 0))
    orchestrator.run_pipeline(ctx)   # 예외 없이 조용히 끝나야 한다

    assert sent == ['20260720']


def test_pipeline_stops_without_warning_on_holiday(monkeypatch):
    """휴장은 정상 상태다 — 경고를 보내지 않는다."""
    from src.pipeline import orchestrator

    _stub_workers(monkeypatch)
    sent = []
    monkeypatch.setattr(orchestrator, '_notify_holiday_check_failed',
                        lambda ctx: sent.append(ctx.today_str))
    monkeypatch.setattr(PipelineContext, 'is_trading_day', lambda self: False)

    orchestrator.run_pipeline(ctx_at(datetime(2026, 7, 17, 10, 0)))

    assert sent == []


def test_warning_bypasses_should_notify(monkeypatch):
    """경고는 should_notify()의 정각 제한을 타지 않는다.

    15/30/45분 런에서 침묵하면 장애를 놓친다.
    """
    from src.pipeline import orchestrator

    monkeypatch.setattr(PipelineContext, 'should_notify',
                        lambda self: (_ for _ in ()).throw(
                            AssertionError("경고는 should_notify를 호출하면 안 된다")))

    messages = []

    class _FakeTelegram:
        def send_message(self, text, parse_mode="HTML"):
            messages.append(text)
            return True

    monkeypatch.setattr('src.telegram_manager.TelegramManager',
                        lambda *a, **k: _FakeTelegram())

    ctx = ctx_at(datetime(2026, 7, 20, 10, 45))   # 정각이 아닌 런
    orchestrator._notify_holiday_check_failed(ctx)

    assert len(messages) == 1
    assert '휴장 판정 실패' in messages[0]
    assert 'FORCE_RUN' in messages[0] or 'force_run' in messages[0]


def test_warning_includes_real_buy_risk_disclosure(monkeypatch):
    """경고가 '수동 실행하라'고만 하면, KIS 점검으로 판정 불가일 때

    운영자가 실제 휴장일에도 그대로 실행해 실매수가 나갈 수 있다.
    경고문에 실매수 위험 고지가 반드시 포함돼야 한다.
    """
    from src.pipeline import orchestrator

    messages = []

    class _FakeTelegram:
        def send_message(self, text, parse_mode="HTML"):
            messages.append(text)
            return True

    monkeypatch.setattr('src.telegram_manager.TelegramManager',
                        lambda *a, **k: _FakeTelegram())

    ctx = ctx_at(datetime(2026, 7, 20, 10, 45))
    orchestrator._notify_holiday_check_failed(ctx)

    assert len(messages) == 1
    assert '실매수' in messages[0]
    assert '휴장일이 아님을' in messages[0] or '휴장일이 아닌지' in messages[0]


def test_warning_send_failure_is_logged(monkeypatch):
    """send_message가 False를 반환하면(예: 텔레그램 자격증명 없음) 조용히

    사라지지 않고 ctx.log에 남아야 한다.
    """
    from src.pipeline import orchestrator

    class _FailingTelegram:
        def send_message(self, text, parse_mode="HTML"):
            return False

    monkeypatch.setattr('src.telegram_manager.TelegramManager',
                        lambda *a, **k: _FailingTelegram())

    logs = []
    ctx = ctx_at(datetime(2026, 7, 20, 10, 45))
    ctx.log = lambda msg: logs.append(msg)

    orchestrator._notify_holiday_check_failed(ctx)

    assert any('발송에 실패' in m for m in logs)
