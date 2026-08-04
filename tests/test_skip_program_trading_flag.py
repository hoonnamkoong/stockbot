"""E3 (2026-08-04 스크래퍼 지연 재설계): TradeEngineWorker.run()의 skip_program_trading.

Stage 0.5에서 버즈 불필요 심이 이미 스크래핑 전에 매매를 마쳤으면
(orchestrator.program_traded_early=True), Stage 3의 run()은 program_trader를
다시 부르지 않는다 — 원장 중복가드가 막아주긴 해도 불필요한 GitHub API
왕복이다. 기본값(False)에서는 기존과 동일하게 항상 호출한다.
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data.schemas import StockData, SyncState
from src.pipeline.workers.trade_engine import TradeEngineWorker


class _FakeCtx:
    def __init__(self):
        self.now_kst = datetime(2026, 8, 4, 11, 20, tzinfo=timezone(timedelta(hours=9)))

    def is_buy_window(self):
        return True

    def is_market_hours(self):
        return True

    def should_notify(self):
        return False  # advisor/balance 경로(매도 후보 선정)를 건너뛴다

    def log(self, msg):
        pass


def _stock():
    return StockData(code='005930', name='삼성전자', price=70000, status='활성')


def _run(skip: bool):
    ctx = _FakeCtx()
    storage = mock.MagicMock()
    worker = TradeEngineWorker(ctx, storage)
    sync_state = SyncState()

    fake_engine = mock.MagicMock()
    fake_engine.execute_simulation.return_value = [
        {'code': '005930', 'name': '삼성전자', 'signal': 'WATCH'}
    ]

    with mock.patch('src.strategy.engine.StrategyEngine', return_value=fake_engine), \
         mock.patch.object(worker, '_run_simulators'), \
         mock.patch('src.pipeline.workers.program_trader.run_program_trading') as rpt_mock:
        worker.run([_stock()], sync_state, skip_program_trading=skip)
        return rpt_mock


def test_program_trading_called_by_default():
    rpt_mock = _run(skip=False)
    rpt_mock.assert_called_once()


def test_program_trading_skipped_when_already_ran_early():
    rpt_mock = _run(skip=True)
    rpt_mock.assert_not_called()
