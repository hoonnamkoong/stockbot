"""오늘 트리거 분리·sticky universe가 만든 회귀 두 건에 대한 회귀 테스트."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime

import pytest

from src.pipeline.context import PipelineContext


def ctx_at(monkeypatch, when: datetime, trading_day=True):
    ctx = object.__new__(PipelineContext)
    ctx.now_kst = when
    monkeypatch.setattr(PipelineContext, 'is_trading_day', lambda self: trading_day)
    return ctx


# ── 1. 마감 후 판정: 리베로 EOD 확정이 도는 조건 ──

@pytest.mark.parametrize('hhmm,expected', [
    ((15, 29), False),   # 아직 장중
    ((15, 30), True),    # 마감 시각
    ((15, 35), True),    # Tasker 마지막 런의 리베로 실행 시각
    ((19, 0), True),
    ((9, 0), False),
])
def test_is_after_market_close_boundaries(monkeypatch, hhmm, expected):
    ctx = ctx_at(monkeypatch, datetime(2026, 7, 10, *hhmm))
    assert ctx.is_after_market_close() is expected


def test_is_after_market_close_false_on_weekend(monkeypatch):
    ctx = ctx_at(monkeypatch, datetime(2026, 7, 11, 16, 0))  # 토요일
    assert ctx.is_after_market_close() is False


def test_is_after_market_close_false_on_holiday(monkeypatch):
    ctx = ctx_at(monkeypatch, datetime(2026, 7, 10, 16, 0), trading_day=False)
    assert ctx.is_after_market_close() is False


def test_market_close_and_market_hours_overlap(monkeypatch):
    """15:35엔 둘 다 참이다. 그래서 분기 순서가 동작을 결정한다."""
    ctx = ctx_at(monkeypatch, datetime(2026, 7, 10, 15, 35))
    assert ctx.is_after_market_close() is True
    assert ctx.is_market_hours() is True


# ── 2. 리베로 분기 결정 ──

def test_libero_action_prefers_finalize_when_both_true():
    """마감 후 확정이 장중 나우캐스트보다 우선한다. 순서가 뒤집히면 EOD가 영영 안 돈다."""
    from src.pipeline.workers.trade_engine import libero_action
    assert libero_action(after_close=True, market_hours=True) == 'finalize'


def test_libero_action_nowcast_during_market():
    from src.pipeline.workers.trade_engine import libero_action
    assert libero_action(after_close=False, market_hours=True) == 'nowcast'


def test_libero_action_none_outside_session():
    from src.pipeline.workers.trade_engine import libero_action
    assert libero_action(after_close=False, market_hours=False) is None


# ── 3. 추적 종목이 리포트·누적 보드로 새지 않는다 ──

def test_active_only_filters_dicts():
    """NotifierWorker는 dict 목록을 받는다. active_only가 dict도 걸러야 한다."""
    from src.pipeline.orchestrator import active_only

    rows = [
        {'code': '111111', 'status': '활성'},
        {'code': '222222', 'status': '추적'},
        {'code': '333333'},                      # status 없음 = 활성
    ]
    assert [r['code'] for r in active_only(rows)] == ['111111', '333333']


def test_active_only_still_filters_objects():
    from src.data.schemas import StockData
    from src.pipeline.orchestrator import active_only

    stocks = [
        StockData(code='111111', name='활성', status='활성'),
        StockData(code='222222', name='추적', status='추적'),
    ]
    assert [s.code for s in active_only(stocks)] == ['111111']
