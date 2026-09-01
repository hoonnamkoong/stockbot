"""오전/오후 세션은 **시계가 아니라 브리핑 슬롯**에서 나온다.

2026-08-31에 상태 기록 게이트를 리포트 슬롯(11:00·14:00)에서 브리핑
슬롯(12:00·15:00)으로 옮겼다. 그런데 세션 판정은 `now_kst.hour < 12`로
남아 있었다 — 슬롯이 12:00부터 열리므로 **오전이 영영 False**가 되고
morning_reported_info가 다시는 안 쌓인다. 로그도 12:05에 "[오후 세션]"이라
찍혔다. 이 상태는 db-data를 왕복해 대시보드로 간다.

12:00 브리핑이 곧 오전 세션이다 — 그 브리핑이 요약하는 구간이 09:00~12:00이다.
슬롯이 또 움직여도 깨지지 않도록 슬롯 문자열에서 세션을 끌어낸다.
"""
import os
import sys
from datetime import datetime
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.trade_engine import TradeEngineWorker  # noqa: E402
from src.data.schemas import StockData  # noqa: E402


@pytest.fixture(autouse=True)
def chdir_tmp(tmp_path, monkeypatch):
    """pick_features 로깅(2.5단계)이 실제 data/를 오염시키지 않도록 격리한다."""
    monkeypatch.chdir(tmp_path)


class _Ctx:
    """now_kst와 슬롯 상태 파일 위치만 통제한다."""

    cycle_id = 12345

    def __init__(self, now, data_dir):
        self.now_kst = now
        self._report_data_dir = data_dir
        self.logs = []

    def is_buy_window(self):
        return True

    def is_market_hours(self):
        return False

    def log(self, msg):
        self.logs.append(msg)


def _sync():
    return mock.MagicMock(daily_deep_dive_codes=[], daily_reported_info=[],
                          morning_reported_info=[], afternoon_reported_info=[])


def _run_at(now, data_dir):
    """주어진 시각에 Stage 3을 한 번 돌리고 (ctx, sync_state)를 돌려준다."""
    ctx = _Ctx(now, str(data_dir))
    w = TradeEngineWorker(ctx, mock.MagicMock())
    stocks = [StockData(code='005930', name='삼성전자', price=10000,
                        fact_score=0.9, tick_power=150.0)]
    sync_state = _sync()

    with mock.patch('src.strategy.engine.StrategyEngine') as MockEngine, \
         mock.patch.object(w, '_run_simulators'):
        MockEngine.return_value.execute_simulation.return_value = [
            {'code': '005930', 'name': '삼성전자', 'signal': 'BUY', 'reason': 'test'}]
        w.run(stocks, sync_state, skip_program_trading=True)

    return ctx, sync_state


def test_noon_slot_is_the_morning_session(tmp_path):
    """12:05 — 12:00 슬롯이 열려 있다. 이건 오전 세션이다.

    `hour < 12`로 재던 시절에는 여기가 오후로 기록됐고, 그 결과
    morning_reported_info가 영원히 비어 있었다."""
    ctx, state = _run_at(datetime(2026, 8, 10, 12, 5), tmp_path)

    assert [i['code'] for i in state.morning_reported_info] == ['005930']
    assert state.afternoon_reported_info == []
    assert any('[오전 세션]' in m for m in ctx.logs), ctx.logs


def test_close_slot_is_the_afternoon_session(tmp_path):
    ctx, state = _run_at(datetime(2026, 8, 10, 15, 5), tmp_path)

    assert [i['code'] for i in state.afternoon_reported_info] == ['005930']
    assert state.morning_reported_info == []
    assert any('[오후 세션]' in m for m in ctx.logs), ctx.logs


def test_outside_a_slot_nothing_is_recorded(tmp_path):
    """13:00은 어느 브리핑 슬롯도 아니다 — 세션 이름을 붙이지도 않는다."""
    ctx, state = _run_at(datetime(2026, 8, 10, 13, 0), tmp_path)

    assert state.morning_reported_info == []
    assert state.afternoon_reported_info == []
    assert any('브리핑 슬롯 아님' in m for m in ctx.logs), ctx.logs
    assert not any('세션]' in m for m in ctx.logs), ctx.logs
