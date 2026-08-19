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
         mock.patch.object(orchestrator, 'selected_sim_and_buzz',
                           return_value=('sim4_bull_daytrading', buzz_needed)), \
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


# ── 배포 제외 (2026-08-09) ──────────────────────────────────────────
# Stage 3 제외는 "그 심을 다시 계산하지 않는다"일 뿐이다. 배포 스텝의
# `cp data/*.json`은 심을 돌렸는지와 무관하게 파일을 올리는데, 그 파일은 이 런이
# 시작할 때 db-data에서 받아온 4~5분 전 사본이다. db_data_repo는 배포 시점에 새로
# clone하므로 그 사이 trading.yml이 push한 최신 상태가 들어 있고, cp가 그것을 옛
# 사본으로 덮어쓴다 — 60초 루프 4~5분치가 통째로 되돌아간다(lost update).
# 파일을 안 만드는 것과 파일을 안 올리는 것은 다른 문제다.

def test_deploy_exclude_lists_the_paper_files_trading_owns(tmp_path):
    path = str(tmp_path / 'data' / '.scraper_deploy_exclude')
    names = orchestrator.write_deploy_exclude('sim4_bull_daytrading', path=path)

    assert names, '선택 심의 상태·이력 파일이 제외 목록에 없다'
    with open(path, encoding='utf-8') as f:
        written = f.read().split()
    assert written == names
    assert any(n.endswith('.json') for n in names)
    assert any(n.endswith('.csv') for n in names)


def test_deploy_exclude_is_emptied_when_trading_owns_nothing(tmp_path):
    """남아 있는 옛 목록이 엉뚱한 심을 배포에서 빼면, 그 심은 스크래퍼가
    갱신했는데도 db-data에 영영 도달하지 못한다. 항상 덮어쓴다."""
    path = str(tmp_path / 'data' / '.scraper_deploy_exclude')
    orchestrator.write_deploy_exclude('sim4_bull_daytrading', path=path)
    assert orchestrator.write_deploy_exclude(None, path=path) == []
    with open(path, encoding='utf-8') as f:
        assert f.read().strip() == ''


def test_the_run_writes_the_exclude_list_for_the_buzz_free_set(tmp_path):
    """2026-08-19: 배포 제외 집합은 선택 심 하나가 아니라 국면에서 정해지는
    버즈 불필요 심 전체다(list_buzz_free_sim_ids) — trading.yml이 프로그램
    매매 ON/OFF와 무관하게 이 집합을 60초마다 돌기 때문에, buzz_needed가
    True든 False든 같은 값이 나와야 한다."""
    written = {}
    with mock.patch.object(orchestrator, 'write_deploy_exclude',
                           side_effect=lambda sim_ids, *a, **kw: written.setdefault('ids', sim_ids)):
        _run(buzz_needed=False)
    assert 'sim4_bull_daytrading' in written['ids']

    written.clear()
    with mock.patch.object(orchestrator, 'write_deploy_exclude',
                           side_effect=lambda sim_ids, *a, **kw: written.setdefault('ids', sim_ids)):
        _run(buzz_needed=True)
    assert 'sim4_bull_daytrading' in written['ids'], (
        '선택 심이 버즈 필요라 스크래퍼가 그 심을 직접 매매해도, 다른 버즈 '
        '불필요 심들의 페이퍼 쌍둥이는 여전히 trading.yml 소관이다')


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
         mock.patch.object(orchestrator, 'selected_sim_and_buzz',
                           return_value=('sim10_orchestrator', True)) as needs, \
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
         mock.patch.object(orchestrator, 'selected_sim_and_buzz',
                           return_value=('sim_psych', True)), \
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
         mock.patch.object(orchestrator, 'selected_sim_and_buzz',
                           return_value=('sim_psych', True)), \
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


# ── 국면 인계 (2026-08-08) ──────────────────────────────────────────
# 이 워크플로가 db-data를 체크아웃하는 시점(dispatch +30초)은 trade_loop가 갱신한
# 국면을 push하는 시점(+75초)보다 빠르다. 즉 파일로 읽으면 **정상 경로에서 항상**
# 한 격자 낡은 국면이다. 국면이 소유자를 바꾸는 심(Sim10)에서는 그 어긋남이
# 이중 주문이나 무주문이 된다. 그래서 dispatch가 값을 실어 보낸다.

def _ownership_regime(monkeypatch, file_regime='SIDEWAYS'):
    """소유권 판정에 실제로 들어간 국면 값을 돌려준다.

    read_regime을 통째로 가짜로 바꾸지 않는다 — 인계값 적용이 그 함수 **안**에
    있기 때문이다(2026-08-09). 여기를 mock하면 정작 검사하려는 로직을 건너뛰고
    "orchestrator가 인계값을 쓴다"는 통과가 아무것도 보장하지 않게 된다.
    대신 파일 읽기만 가짜로 두어 진짜 read_regime이 돌게 한다.
    """
    ctx = _Ctx()
    with mock.patch.object(orchestrator, 'TradeEngineWorker') as tw, \
         mock.patch.object(orchestrator, 'StorageManager') as sm, \
         mock.patch.object(orchestrator, 'DataFetcherWorker') as df, \
         mock.patch.object(orchestrator, 'LLMAnalyzerWorker'), \
         mock.patch.object(orchestrator, 'NotifierWorker'), \
         mock.patch('src.strategy.regime_state.read_regime_state',
                    return_value={'current_regime': file_regime, 'bull_score': 50.0}), \
         mock.patch.object(orchestrator, 'read_regime_state',
                           return_value={'current_regime': file_regime}), \
         mock.patch.object(orchestrator, 'selected_sim_and_buzz',
                           return_value=('sim4_bull_daytrading', False)) as needs, \
         mock.patch.object(orchestrator.scrape_gate, 'mark_scraped'):
        _full_run_mocks(tw, sm, df)
        orchestrator.run_pipeline(ctx)
    return needs.call_args[0][1]


def test_prefers_the_regime_handed_over_by_trading_yml(monkeypatch):
    monkeypatch.setenv('REGIME_HINT', 'BULL')
    assert _ownership_regime(monkeypatch, file_regime='SIDEWAYS') == 'BULL'


def test_falls_back_to_the_file_when_nothing_was_handed_over(monkeypatch):
    """수동 실행에는 인계값이 없다. 한 격자 낡았어도 값이 있는 편이 낫다."""
    monkeypatch.delenv('REGIME_HINT', raising=False)
    assert _ownership_regime(monkeypatch, file_regime='SIDEWAYS') == 'SIDEWAYS'


def test_blank_hint_is_not_a_regime(monkeypatch):
    """GitHub은 미지정 입력을 빈 문자열로 채운다 — 빈 값을 국면으로 읽으면
    '측정 불가'가 아니라 '알 수 없는 국면'이 되어 판정이 예외로 떨어진다."""
    monkeypatch.setenv('REGIME_HINT', '')
    assert _ownership_regime(monkeypatch, file_regime='SIDEWAYS') == 'SIDEWAYS'


# ── 페이퍼 쌍둥이의 writer도 하나다 (2026-08-08) ────────────────────

def test_the_sim_owned_by_trading_yml_is_excluded_from_stage3():
    """trading.yml은 버즈 불필요 심 전체(선택 여부 무관)의 페이퍼 쌍둥이를
    60초마다 갱신하고 배포한다. 여기서 같은 심들을 런 시작 시점 스냅샷으로
    다시 돌려 data/*.json을 통째로 밀면 그 4~5분치가 되돌아간다."""
    tw, _ = _run(buzz_needed=False)

    excluded = tw.return_value.run.call_args.kwargs['paper_owned_elsewhere']
    assert 'sim4_bull_daytrading' in excluded


def test_buzz_free_set_is_still_excluded_when_the_scraper_owns_the_trading():
    """2026-08-19: 선택 심이 버즈 필요라 스크래퍼가 그 심을 직접 매매해도,
    Sim2/3/4/6/8/9 같은 버즈 불필요 심들의 페이퍼 쌍둥이는 여전히
    trading.yml 소관이다 — 이 집합은 국면에서 정해지지, 선택 심 매매 여부와
    무관하다(list_buzz_free_sim_ids)."""
    tw, _ = _run(buzz_needed=True)

    excluded = tw.return_value.run.call_args.kwargs['paper_owned_elsewhere']
    assert excluded, '버즈 필요 심을 스크래퍼가 매매해도 버즈 불필요 심들은 여전히 제외돼야 한다'
    assert 'sim_spillover' in excluded, 'Sim2 같은 버즈 불필요 심은 선택 심과 무관하게 제외돼야 한다'


def test_buzz_free_set_is_still_excluded_when_ownership_is_undecidable():
    """프로그램 매매 소유권을 못 정해도(선택 심 조회 실패 등), 국면에서 정해지는
    버즈 불필요 심 전체는 그대로 trading.yml 소관이다 — 이 둘은 별개 판단이다."""
    tw, _ = _run(buzz_needed=None)

    excluded = tw.return_value.run.call_args.kwargs['paper_owned_elsewhere']
    assert excluded, '소유권 판정 불가와 무관하게 버즈 불필요 심들은 제외돼야 한다'
