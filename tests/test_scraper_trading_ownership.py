"""scraper.yml은 **버즈 필요 심만** 매매한다. 국면은 읽기만 한다.

2026-08-08 구조 변경. 태스커 → trading.yml → (10분 격자일 때만) scraper.yml.
실전 주문의 소유자는 어느 순간에도 하나다:

    needs_buzz == False → trading.yml (60초 루프)
    needs_buzz == True  → 이 워크플로 Stage 3 (그 심의 입력이 스크래핑 결과다)

이 파일은 그 소유권 규칙과, 국면을 여기서 갱신하지 않는다는 것을 못박는다.

**앞선 사양의 교훈** (이 파일의 전신인 test_scraper_offtick_gate.py):
오프틱 매매를 trading_lite.yml에 위임했고 단위 테스트는 "위임한다"를 정확히
검증했는데, **위임 대상이 실재하는지는 아무도 검증하지 않았다.** 그 워크플로는
한 번도 불린 적이 없었고(태스커는 workflow_dispatch를 보내는데 그건 지정한
워크플로 하나에만 도달한다) 실전 매매가 하루 종일 12분 간격으로 돌았다.
실행 이력 0건인 워크플로는 어떤 실패 목록에도 안 뜬다.
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
    today_display = '2026-08-10'
    today_str = '2026-08-10'

    def __init__(self, trading=True):
        self.now_kst = datetime(2026, 8, 10, 10, 32, tzinfo=KST)
        self.cycle_id = 900000
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


def _full_run_mocks(tw, storage_cls, df):
    tw.return_value.run.return_value = ([], [], None)
    df.return_value.run.return_value = []
    fake_sync_state = mock.MagicMock(daily_reported_info=[])
    storage_cls.return_value.load_sync_state.return_value = (fake_sync_state, {})


def _run(buzz_needed, regime='BULL'):
    """run_pipeline을 최소 스텁으로 돌리고 (TradeEngineWorker mock, ctx)를 돌려준다."""
    ctx = _Ctx()
    with mock.patch.object(orchestrator, 'TradeEngineWorker') as tw, \
         mock.patch.object(orchestrator, 'StorageManager') as sm, \
         mock.patch.object(orchestrator, 'DataFetcherWorker') as df, \
         mock.patch.object(orchestrator, 'LLMAnalyzerWorker'), \
         mock.patch.object(orchestrator, 'NotifierWorker'), \
         mock.patch.object(orchestrator, 'read_regime', return_value=(regime, 60.0)), \
         mock.patch.object(orchestrator, 'selected_sim_needs_buzz',
                           return_value=buzz_needed), \
         mock.patch.object(orchestrator.scrape_gate, 'mark_scraped'):
        _full_run_mocks(tw, sm, df)
        orchestrator.run_pipeline(ctx)
    return tw, ctx


# ── 소유권 ──────────────────────────────────────────────────────────

def test_scraper_trades_when_the_selected_sim_needs_buzz():
    """버즈 필요 심의 입력은 스크래핑 결과다 — 여기 말고는 낼 수 있는 곳이 없다."""
    tw, _ = _run(buzz_needed=True)

    assert tw.return_value.run.call_args.kwargs['skip_program_trading'] is False


def test_scraper_does_not_trade_when_the_sim_is_buzz_free():
    """버즈 불필요 심은 trading.yml이 60초 루프로 낸다. 여기서도 내면 같은
    사이클에 주문이 두 번 나갈 수 있다 — 두 워크플로는 concurrency 그룹이
    달라 실제로 동시에 돈다."""
    tw, _ = _run(buzz_needed=False)

    assert tw.return_value.run.call_args.kwargs['skip_program_trading'] is True


def test_scraper_does_not_trade_when_ownership_is_undecidable():
    """선택 심을 못 읽거나 needs_buzz 판정이 실패하면 아무도 매매하지 않는다.
    모르는 채로 주문하는 것보다 한 사이클 쉬는 게 낫다."""
    tw, _ = _run(buzz_needed=None)

    assert tw.return_value.run.call_args.kwargs['skip_program_trading'] is True


# ── 국면 ────────────────────────────────────────────────────────────

def test_scraper_never_updates_the_regime():
    """국면 writer는 trade_loop 하나다. 두 곳에서 갱신하면 같은 순간이
    regime_history에 두 번 누적되어 평활이 왜곡된다."""
    tw, _ = _run(buzz_needed=True)

    tw.return_value.run_regime_stage.assert_not_called()


def test_ownership_is_decided_with_the_regime_that_was_read():
    """Sim10은 needs_buzz=dynamic이라 국면이 소유권을 바꾼다 — 읽어온 국면이
    그대로 판정에 들어가야 한다."""
    ctx = _Ctx()
    with mock.patch.object(orchestrator, 'TradeEngineWorker') as tw, \
         mock.patch.object(orchestrator, 'StorageManager') as sm, \
         mock.patch.object(orchestrator, 'DataFetcherWorker') as df, \
         mock.patch.object(orchestrator, 'LLMAnalyzerWorker'), \
         mock.patch.object(orchestrator, 'NotifierWorker'), \
         mock.patch.object(orchestrator, 'read_regime', return_value=('SIDEWAYS', 50.0)), \
         mock.patch.object(orchestrator, 'selected_sim_needs_buzz',
                           return_value=True) as needs, \
         mock.patch.object(orchestrator.scrape_gate, 'mark_scraped'):
        _full_run_mocks(tw, sm, df)
        orchestrator.run_pipeline(ctx)

    assert needs.call_args[0][1] == 'SIDEWAYS'


# ── 게이트 상태 기록 ────────────────────────────────────────────────

def test_successful_run_marks_scraped():
    """이 상태를 trade_loop가 읽어 '스크래퍼를 부를 차례인가'를 정한다."""
    ctx = _Ctx()
    with mock.patch.object(orchestrator, 'TradeEngineWorker') as tw, \
         mock.patch.object(orchestrator, 'StorageManager') as sm, \
         mock.patch.object(orchestrator, 'DataFetcherWorker') as df, \
         mock.patch.object(orchestrator, 'LLMAnalyzerWorker'), \
         mock.patch.object(orchestrator, 'NotifierWorker'), \
         mock.patch.object(orchestrator, 'read_regime', return_value=('BULL', 60.0)), \
         mock.patch.object(orchestrator, 'selected_sim_needs_buzz', return_value=True), \
         mock.patch.object(orchestrator.scrape_gate, 'mark_scraped') as mark:
        _full_run_mocks(tw, sm, df)
        orchestrator.run_pipeline(ctx)

    mark.assert_called_once_with(ctx.now_kst)


def test_failed_run_does_not_mark_scraped():
    """Stage 1이 죽으면 mark_scraped까지 도달하면 안 된다 — 기록해버리면
    trade_loop가 '방금 했다'로 읽어 다음 격자까지 재시도하지 않는다."""
    ctx = _Ctx()
    with mock.patch.object(orchestrator, 'TradeEngineWorker'), \
         mock.patch.object(orchestrator, 'StorageManager'), \
         mock.patch.object(orchestrator, 'DataFetcherWorker') as df, \
         mock.patch.object(orchestrator, 'read_regime', return_value=('BULL', 60.0)), \
         mock.patch.object(orchestrator, 'selected_sim_needs_buzz', return_value=True), \
         mock.patch.object(orchestrator.scrape_gate, 'mark_scraped') as mark:
        df.return_value.run.side_effect = RuntimeError('네이버 다운')
        try:
            orchestrator.run_pipeline(ctx)
        except RuntimeError:
            pass

    mark.assert_not_called()


def test_holiday_stops_before_anything():
    ctx = _Ctx(trading=False)
    with mock.patch.object(orchestrator, 'TradeEngineWorker') as tw, \
         mock.patch.object(orchestrator, 'StorageManager'), \
         mock.patch.object(orchestrator, 'DataFetcherWorker') as df:
        orchestrator.run_pipeline(ctx)

    tw.assert_not_called()
    df.assert_not_called()
