"""cycle_id — 서로 다른 런·서로 다른 심의 관측을 "같은 시각"으로 묶는 격자 번호.

이게 없으면 각 심이 각자 datetime.now()를 찍어 수 초씩 어긋나고, 심1 vs 심1-1
비교(같은 순간에 서로 다른 판단을 했는가)와 forward return용 t+N 조인이 둘 다
성립하지 않는다. 조인 키는 조용히 깨지는 종류의 것이라 배선 자체를 테스트한다.
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data import sim_diag
from src.pipeline import orchestrator, trading_cycle
from src.pipeline.context import PipelineContext, CYCLE_SECONDS

KST = timezone(timedelta(hours=9))


class _Ctx:
    VERSION = 'test'
    today_display = '2026-08-10'
    today_str = '2026-08-10'

    def __init__(self, cycle_id=12345):
        self.now_kst = datetime(2026, 8, 10, 10, 32, tzinfo=KST)
        self.cycle_id = cycle_id
        self.logs = []

    def is_trading_day(self):
        return True

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


# ── 값 자체 ────────────────────────────────────────────────────────────

def test_cycle_id_is_utc_epoch_grid_not_local_time():
    """naive KST datetime에 .timestamp()를 쓰면 실행 머신의 로컬 타임존으로
    해석되어 어긋난다. epoch 초에는 타임존이 없다 — UTC에서 바로 나눠야 한다.

    이 테스트는 로컬 타임존이 KST가 아닌 머신(CI는 UTC)에서도 통과해야 한다.
    """
    before = int(datetime.now(timezone.utc).timestamp()) // CYCLE_SECONDS
    ctx = PipelineContext()
    after = int(datetime.now(timezone.utc).timestamp()) // CYCLE_SECONDS

    assert before <= ctx.cycle_id <= after

    # 함정 재현: naive KST를 재료로 쓰면 로컬 타임존에 따라 값이 달라진다.
    naive_kst_based = int(ctx.now_kst.timestamp()) // CYCLE_SECONDS
    assert ctx.now_kst.tzinfo is None
    if naive_kst_based != ctx.cycle_id:
        # 로컬이 KST가 아니면 실제로 어긋난다 — 그래서 그 방식을 안 쓴다.
        assert abs(naive_kst_based - ctx.cycle_id) > 0


def test_same_context_gives_one_cycle_id():
    """now_kst와 cycle_id는 시계를 한 번만 읽어야 한다 — 각자 읽으면 격자
    경계에서 갈린다."""
    ctx = PipelineContext()
    expected = int(
        (ctx.now_kst - timedelta(hours=9)).replace(tzinfo=timezone.utc).timestamp()
    ) // CYCLE_SECONDS
    assert ctx.cycle_id == expected


def test_grid_width_matches_tasker_period():
    """격자가 태스커 주기보다 촘촘하면 비고, 성글면 한 격자에 여러 관측이 겹쳐
    조인이 1:N이 된다."""
    assert CYCLE_SECONDS == 120


# ── 배선 ───────────────────────────────────────────────────────────────

def _reset_cycle():
    sim_diag.set_cycle(None)


def test_run_pipeline_sets_the_cycle():
    _reset_cycle()
    ctx = _Ctx(cycle_id=999)
    with mock.patch.object(orchestrator, 'TradeEngineWorker') as tw, \
         mock.patch.object(orchestrator, 'StorageManager') as sm, \
         mock.patch.object(orchestrator, 'DataFetcherWorker') as df, \
         mock.patch.object(orchestrator, 'LLMAnalyzerWorker'), \
         mock.patch.object(orchestrator, 'NotifierWorker'), \
         mock.patch.object(orchestrator, 'read_regime', return_value=('BULL', 60.0)), \
         mock.patch.object(orchestrator, 'selected_sim_and_buzz',
                           return_value=(None, None)), \
         mock.patch.object(orchestrator.scrape_gate, 'mark_scraped'):
        tw.return_value.run.return_value = ([], [], None)
        df.return_value.run.return_value = []
        sm.return_value.load_sync_state.return_value = (
            mock.MagicMock(daily_reported_info=[]), {})
        orchestrator.run_pipeline(ctx)

    assert sim_diag._cycle_id == 999


def test_trade_only_cycle_sets_the_cycle_on_its_own():
    """매매 루프가 단독 진입점으로 부를 때도 조인 키가 붙어야 한다."""
    _reset_cycle()
    ctx = _Ctx(cycle_id=777)
    with mock.patch.object(trading_cycle, 'TradeEngineWorker'), \
         mock.patch.object(trading_cycle, 'read_regime', return_value=('BULL', 60.0)), \
         mock.patch.object(trading_cycle, 'trade_if_buzz_free', return_value=(None, None)):
        trading_cycle.run_trade_only_cycle(ctx, mock.MagicMock())

    assert sim_diag._cycle_id == 777


# ── 기록 ───────────────────────────────────────────────────────────────

def test_append_stamps_every_row_with_the_same_cycle(tmp_path):
    """한 사이클의 모든 행은 같은 번호를 받는다 — 이게 조인의 전제다."""
    sim_diag.set_cycle(4242)
    path = str(tmp_path / 'diag.csv')
    n = sim_diag.append('sim1', [{'code': '005930'}, {'code': '000660'}], path=path)

    assert n == 2
    import csv
    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    assert [r['cycle_id'] for r in rows] == ['4242', '4242']


def test_unset_cycle_leaves_the_key_blank_not_guessed(tmp_path):
    """세팅 안 됐으면 빈칸으로 둔다. 여기서 시계를 다시 읽어 추정하면 런이
    격자 경계를 넘을 때 같은 사이클 행들이 다른 번호를 받아 조인이 조용히
    깨진다 — 빈칸은 눈에 보이지만 어긋난 번호는 안 보인다."""
    _reset_cycle()
    path = str(tmp_path / 'diag.csv')
    sim_diag.append('sim1', [{'code': '005930'}], path=path)

    import csv
    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    assert rows[0]['cycle_id'] == ''


def test_explicit_cycle_id_in_record_wins(tmp_path):
    """행이 자기 번호를 갖고 오면 그걸 쓴다(승계·재기록 경로)."""
    sim_diag.set_cycle(4242)
    path = str(tmp_path / 'diag.csv')
    sim_diag.append('sim1', [{'code': '005930', 'cycle_id': 111}], path=path)

    import csv
    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    assert rows[0]['cycle_id'] == '111'
