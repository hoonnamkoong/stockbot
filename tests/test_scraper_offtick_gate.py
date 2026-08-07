"""run_pipeline의 오프틱 경로가 "매매는 하되 스크래핑·국면갱신은 안 한다"인지.

태스커가 2분마다 부르지만 스크래핑은 10분에 한 번만 한다. 오프틱에 Stage 0
(국면 갱신)까지 돌면 국면 이력이 오염되고 KIS 콜이 폭증한다.

**2026-08-08 사양 변경.** 이 파일은 원래 "오프틱은 아무것도 안 한다"를 못박고
있었다(`test_offtick_never_touches_trade_engine_worker`). 그 위임 대상이던
trading_lite.yml이 **한 번도 불린 적이 없다는 게 실측으로 드러났다** — 태스커는
repository_dispatch가 아니라 workflow_dispatch를 보내고, 그건 지정한 워크플로
하나에만 도달한다. 그래서 오프틱 5/6이 아무 일도 안 했고 실전 매매 간격이
10분에서 12분으로 늘어났다.

교훈: 단위 테스트는 "위임한다"를 검증했지만 **위임 대상이 실재하는지는 아무도
검증하지 않았다.** 실행 이력 0건인 워크플로는 어떤 실패 목록에도 안 뜬다.
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


def test_offtick_trades_but_does_not_scrape_or_update_regime():
    """오프틱은 매매를 한다. 단 스크래핑과 국면 갱신은 하지 않는다.

    이 셋을 한 테스트에 묶은 건 의도적이다 — "매매한다"만 보면 국면 갱신이
    슬쩍 딸려 들어와도 통과하고, "국면 갱신 안 한다"만 보면 08-07처럼 매매까지
    같이 죽어도 통과한다. 두 실패가 서로를 가린다.
    """
    ctx = _Ctx()
    with mock.patch.object(orchestrator, 'TradeEngineWorker') as tw, \
         mock.patch.object(orchestrator, 'StorageManager'), \
         mock.patch.object(orchestrator, 'DataFetcherWorker') as df, \
         mock.patch.object(orchestrator, 'LLMAnalyzerWorker'), \
         mock.patch.object(orchestrator, 'NotifierWorker'), \
         mock.patch.object(orchestrator, 'read_regime', return_value=('BULL', 60.0)), \
         mock.patch.object(orchestrator, 'trade_if_buzz_free', return_value=None) as tbf, \
         mock.patch.object(orchestrator.scrape_gate, 'is_scrape_due', return_value=False), \
         mock.patch.object(orchestrator.scrape_gate, 'mark_scraped') as mark:
        orchestrator.run_pipeline(ctx)

    tbf.assert_called_once()                              # 매매는 한다
    assert tbf.call_args[0][2] == 'BULL'                  # 읽어온 국면을 그대로 넘긴다
    tw.return_value.run_regime_stage.assert_not_called()  # 국면 갱신은 안 한다
    df.assert_not_called()                                # 스크래핑도 안 한다
    mark.assert_not_called()
    assert any('오프틱' in m for m in ctx.logs)


def test_offtick_syncs_only_the_traded_sims_paper_twin():
    """실전이 돈 심의 페이퍼 쌍둥이만 같은 주기로 갱신한다.

    안 그러면 대시보드의 페이퍼 성과가 실제 계좌와 갈라져서 '승자를 뽑아 실전에
    올린다'는 방식의 근거가 무너진다.
    """
    ctx = _Ctx()
    with mock.patch.object(orchestrator, 'TradeEngineWorker') as tw, \
         mock.patch.object(orchestrator, 'StorageManager'), \
         mock.patch.object(orchestrator, 'DataFetcherWorker'), \
         mock.patch.object(orchestrator, 'LLMAnalyzerWorker'), \
         mock.patch.object(orchestrator, 'NotifierWorker'), \
         mock.patch.object(orchestrator, 'read_regime', return_value=('BULL', 60.0)), \
         mock.patch.object(orchestrator, 'trade_if_buzz_free', return_value='sim4_1'), \
         mock.patch.object(orchestrator.scrape_gate, 'is_scrape_due', return_value=False), \
         mock.patch.object(orchestrator.scrape_gate, 'mark_scraped'):
        orchestrator.run_pipeline(ctx)

    tw.return_value._run_simulators.assert_called_once_with(
        [], only_sim_id='sim4_1', allow_price_fallback=False)


def test_offtick_paper_sync_failure_does_not_break_the_run():
    """페이퍼 동기화가 죽어도 매매는 이미 끝났다 — 예외가 런을 실패로 만들면
    안 된다(실패한 런은 배포 스텝을 건너뛴다)."""
    ctx = _Ctx()
    with mock.patch.object(orchestrator, 'TradeEngineWorker') as tw, \
         mock.patch.object(orchestrator, 'StorageManager'), \
         mock.patch.object(orchestrator, 'DataFetcherWorker'), \
         mock.patch.object(orchestrator, 'LLMAnalyzerWorker'), \
         mock.patch.object(orchestrator, 'NotifierWorker'), \
         mock.patch.object(orchestrator, 'read_regime', return_value=('BULL', 60.0)), \
         mock.patch.object(orchestrator, 'trade_if_buzz_free', return_value='sim4_1'), \
         mock.patch.object(orchestrator.scrape_gate, 'is_scrape_due', return_value=False), \
         mock.patch.object(orchestrator.scrape_gate, 'mark_scraped'):
        tw.return_value._run_simulators.side_effect = RuntimeError('KIS 다운')
        orchestrator.run_pipeline(ctx)   # 예외가 새어나오면 실패

    assert any('페이퍼 동기화 실패' in m for m in ctx.logs)


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
