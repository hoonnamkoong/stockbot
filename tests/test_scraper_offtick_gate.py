"""run_pipeline이 오프틱에서 실제로 아무것도 안 하는지 (scrape_gate 배선).

2026-08-07에 태스커가 tasker_trigger 하나만 2분마다 보낸다는 게 드러나서,
scraper.yml도 매 2분 호출된다. 오프틱(10분이 안 됐을 때)에 Stage 0(국면 갱신)
까지 돌면, trade_lite 감사에서 잡았던 것과 같은 문제(국면 이력 오염, KIS 콜
폭증)가 scraper.yml에서도 재발한다 — 여기서는 게이트가 Stage 0 진입 자체를
막는지, 그리고 성공적으로 끝까지 돈 사이클만 mark_scraped를 호출하는지 본다.
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline import orchestrator

KST = timezone(timedelta(hours=9))


class _Ctx:
    VERSION = 'test'
    today_display = '2026-08-07'
    today_str = '2026-08-07'

    def __init__(self, trading=True):
        self.now_kst = datetime(2026, 8, 7, 10, 32, tzinfo=KST)
        self._trading = trading
        self.logs = []

    def is_trading_day(self):
        return self._trading

    def is_market_hours(self):
        return True

    def is_buy_window(self):
        return True

    def should_notify(self):
        return False

    def log(self, msg):
        self.logs.append(str(msg))

    def stage(self, name):
        return mock.MagicMock(__enter__=lambda s: None, __exit__=lambda s, *a: False)


def test_offtick_never_touches_trade_engine_worker():
    """오프틱이면 TradeEngineWorker를 아예 만들지 않는다 = Stage 0(국면 갱신)
    자체가 안 돈다."""
    ctx = _Ctx()
    with mock.patch.object(orchestrator, 'TradeEngineWorker') as tw, \
         mock.patch.object(orchestrator, 'StorageManager'), \
         mock.patch.object(orchestrator, 'DataFetcherWorker') as df, \
         mock.patch.object(orchestrator, 'LLMAnalyzerWorker'), \
         mock.patch.object(orchestrator, 'NotifierWorker'), \
         mock.patch.object(orchestrator, 'trade_if_buzz_free', return_value=None), \
         mock.patch.object(orchestrator.scrape_gate, 'is_scrape_due', return_value=False), \
         mock.patch.object(orchestrator.scrape_gate, 'mark_scraped') as mark:
        orchestrator.run_pipeline(ctx)

    tw.assert_not_called()
    df.assert_not_called()
    mark.assert_not_called()
    assert any('오프틱' in m for m in ctx.logs)


def _configure_full_run_mocks(tw, storage_cls, df):
    tw.return_value.run_regime_stage.return_value = 'BULL'
    tw.return_value.run.return_value = ([], [], None)
    df.return_value.run.return_value = []
    fake_sync_state = mock.MagicMock(daily_reported_info=[])
    storage_cls.return_value.load_sync_state.return_value = (fake_sync_state, {})


def test_ontick_runs_full_pipeline_and_marks_scraped():
    ctx = _Ctx()
    with mock.patch.object(orchestrator, 'TradeEngineWorker') as tw, \
         mock.patch.object(orchestrator, 'StorageManager') as sm, \
         mock.patch.object(orchestrator, 'DataFetcherWorker') as df, \
         mock.patch.object(orchestrator, 'LLMAnalyzerWorker'), \
         mock.patch.object(orchestrator, 'NotifierWorker'), \
         mock.patch.object(orchestrator, 'trade_if_buzz_free', return_value=None), \
         mock.patch.object(orchestrator, 'read_regime', return_value=(None, None)), \
         mock.patch.object(orchestrator.scrape_gate, 'is_scrape_due', return_value=True), \
         mock.patch.object(orchestrator.scrape_gate, 'mark_scraped') as mark:
        _configure_full_run_mocks(tw, sm, df)
        orchestrator.run_pipeline(ctx)

    tw.assert_called_once()
    tw.return_value.run_regime_stage.assert_called_once()
    mark.assert_called_once_with(ctx.now_kst)


def test_force_run_bypasses_the_scrape_gate():
    """수동 force_run은 10분 게이트에도 막히면 안 된다 — '지금 당장'이 의도다."""
    ctx = _Ctx()
    with mock.patch.object(orchestrator, 'TradeEngineWorker') as tw, \
         mock.patch.object(orchestrator, 'StorageManager') as sm, \
         mock.patch.object(orchestrator, 'DataFetcherWorker') as df, \
         mock.patch.object(orchestrator, 'LLMAnalyzerWorker'), \
         mock.patch.object(orchestrator, 'NotifierWorker'), \
         mock.patch.object(orchestrator, 'trade_if_buzz_free', return_value=None), \
         mock.patch.object(orchestrator, 'read_regime', return_value=(None, None)), \
         mock.patch.object(orchestrator.scrape_gate, 'is_scrape_due', return_value=False), \
         mock.patch.object(orchestrator.scrape_gate, 'mark_scraped') as mark, \
         mock.patch.dict(os.environ, {'FORCE_RUN': 'true'}):
        _configure_full_run_mocks(tw, sm, df)
        orchestrator.run_pipeline(ctx)

    tw.assert_called_once()
    mark.assert_called_once()


def test_failed_run_does_not_mark_scraped():
    """Stage 1이 죽으면 mark_scraped까지 도달하면 안 된다 — 다음 오프틱 판정이
    '아직 신선함'으로 착각하면 실제로는 갱신 안 된 채로 10분을 더 기다린다."""
    ctx = _Ctx()
    with mock.patch.object(orchestrator, 'TradeEngineWorker') as tw, \
         mock.patch.object(orchestrator, 'StorageManager'), \
         mock.patch.object(orchestrator, 'DataFetcherWorker') as df, \
         mock.patch.object(orchestrator, 'trade_if_buzz_free', return_value=None), \
         mock.patch.object(orchestrator.scrape_gate, 'is_scrape_due', return_value=True), \
         mock.patch.object(orchestrator.scrape_gate, 'mark_scraped') as mark:
        tw.return_value.run_regime_stage.return_value = 'BULL'
        df.return_value.run.side_effect = RuntimeError('네이버 다운')
        try:
            orchestrator.run_pipeline(ctx)
        except RuntimeError:
            pass

    mark.assert_not_called()
