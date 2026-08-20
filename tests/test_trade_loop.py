"""실전 매매 진입점(trade_loop) — 태스커가 직접 부르는 워크플로의 본체.

여기서 고정하는 계약:
  1. 60초 간격으로 예산이 허락하는 만큼 매매를 반복한다(태스커 최소 간격 2분에서
     1분 매매를 얻는 유일한 방법 — 런 하나가 셋업을 한 번만 내고 두 바퀴 돈다).
  2. 국면 갱신과 스크래퍼 dispatch는 10분 격자에서만, 그리고 매매보다 먼저.
     국면을 매 바퀴 갱신하면 평활 시간상수가 10배 짧아진다.
  3. 매매할 게 없으면(OFF·버즈 필요 심·조회 실패) 자지 않고 즉시 끝낸다.
  4. 배포 목록은 루프 끝에 딱 한 번.
"""
import os
import sys
from datetime import datetime
from unittest import mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts import trade_loop


class _Ctx:
    def __init__(self, now=None):
        self.now_kst = now or datetime(2026, 8, 10, 10, 30, 0)
        self.cycle_id = 1
        self.today_display = '2026.08.10'
        self.logs = []

    def is_trading_day(self):
        return True

    def log(self, msg):
        self.logs.append(str(msg))

    def stage(self, name):
        return mock.MagicMock(__enter__=lambda s: None, __exit__=lambda s, *a: False)


# ── 시간 예산 (순수 함수) ────────────────────────────────────────────

def test_two_turns_fit_in_a_tasker_window():
    """이게 '1분 매매'의 전부다. 첫 바퀴 직후(경과 ~0초)에 한 바퀴가 더 들어가야 한다."""
    assert trade_loop.has_budget_for_another_turn(0.0) is True


def test_third_turn_does_not_fit():
    """두 바퀴를 돈 뒤(경과 ~60초)에는 더 돌지 않는다 — 다음 트리거와 겹친다."""
    assert trade_loop.has_budget_for_another_turn(trade_loop.TRADE_INTERVAL_SEC) is False


def test_budget_leaves_room_for_setup_and_deploy():
    """셋업(약 20초) + 예산 + 배포(약 12초)가 태스커 간격(120초)보다 짧아야 한다.
    넘으면 concurrency가 런을 취소해 매매 사이클이 사라진다."""
    assert trade_loop.LOOP_BUDGET_SEC + 20 + 12 < 120


# ── 루프 구조 ───────────────────────────────────────────────────────

@pytest.fixture
def stub(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(trade_loop, 'StorageManager', mock.MagicMock())
    monkeypatch.setattr(trade_loop.time, 'sleep', mock.MagicMock())
    monkeypatch.setattr(trade_loop, 'refresh_regime', mock.MagicMock())
    monkeypatch.setattr(trade_loop, 'dispatch_scraper', mock.MagicMock())
    monkeypatch.setattr(trade_loop.scrape_gate, 'is_scrape_due', lambda *a, **k: False)
    # 게이트 상태 파일은 절대 경로(레포의 data/)를 본다 — 막지 않으면 테스트가
    # 실제 상태 파일을 읽고 쓰며 서로에게 영향을 준다.
    monkeypatch.setattr(trade_loop.scrape_gate, 'is_regime_due', lambda *a, **k: False)
    monkeypatch.setattr(trade_loop.scrape_gate, 'mark_regime', mock.MagicMock())
    # 순위 스냅샷은 KIS를 부른다. 막지 않으면 테스트가 네트워크를 탄다.
    monkeypatch.setattr(trade_loop, 'collect_rank_snapshot', mock.MagicMock(return_value=None))
    monkeypatch.setattr(trade_loop.PipelineContext, 'from_env',
                        classmethod(lambda cls: _Ctx()))
    return monkeypatch


def _budget(monkeypatch, turns: int):
    """정확히 turns 바퀴만 허용하도록 예산 판정을 고정한다."""
    left = {'n': turns - 1}

    def _has(elapsed):
        if left['n'] <= 0:
            return False
        left['n'] -= 1
        return True

    monkeypatch.setattr(trade_loop, 'has_budget_for_another_turn', _has)


def test_repeats_until_the_budget_runs_out(stub):
    cycles = mock.MagicMock(return_value=('sim4_bull_daytrading', set()))
    stub.setattr(trade_loop, 'run_trade_only_cycle', cycles)
    _budget(stub, 2)

    trade_loop.run_trade_loop(_Ctx())

    assert cycles.call_count == 2
    assert trade_loop.time.sleep.call_count == 1


def test_each_turn_gets_a_fresh_context(stub):
    """PipelineContext.now_kst는 생성 시점 고정이다. 재사용하면 15:30 매수
    차단선이 첫 바퀴 시각에 얼어붙어 정규장이 닫힌 뒤에도 매수가 나간다."""
    made = []
    stub.setattr(trade_loop.PipelineContext, 'from_env',
                 classmethod(lambda cls: made.append(1) or _Ctx()))
    stub.setattr(trade_loop, 'run_trade_only_cycle',
                 mock.MagicMock(return_value=('sim4_bull_daytrading', set())))
    _budget(stub, 3)

    trade_loop.run_trade_loop(_Ctx())

    assert len(made) == 2, '2·3바퀴는 새 컨텍스트여야 한다(1바퀴는 인자로 받은 것)'


def test_exits_immediately_when_there_is_nothing_to_trade(stub):
    """OFF·버즈 필요 심·조회 실패는 전부 None이다. 60초를 자며 기다릴 이유가
    없다 — 재시도는 2분 뒤 태스커 하트비트가 한다."""
    cycles = mock.MagicMock(return_value=(None, set()))
    stub.setattr(trade_loop, 'run_trade_only_cycle', cycles)
    _budget(stub, 5)

    trade_loop.run_trade_loop(_Ctx())

    assert cycles.call_count == 1
    trade_loop.time.sleep.assert_not_called()


# ── 10분 격자 ───────────────────────────────────────────────────────

def test_refreshes_regime_and_wakes_scraper_only_when_due(stub):
    stub.setattr(trade_loop.scrape_gate, 'is_scrape_due', lambda *a, **k: True)
    stub.setattr(trade_loop.scrape_gate, 'is_regime_due', lambda *a, **k: True)
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock(return_value=(None, set())))
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    trade_loop.refresh_regime.assert_called_once()
    trade_loop.dispatch_scraper.assert_called_once()


def test_leaves_regime_and_scraper_alone_when_not_due(stub):
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock(return_value=(None, set())))
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    trade_loop.refresh_regime.assert_not_called()
    trade_loop.dispatch_scraper.assert_not_called()


def test_regime_is_refreshed_before_trading(stub):
    """매매가 국면을 읽어 소유권을 정한다 — 갱신이 뒤에 오면 이번 런 전체가
    한 사이클 낡은 국면으로 판단한다."""
    order = []
    stub.setattr(trade_loop.scrape_gate, 'is_scrape_due', lambda *a, **k: True)
    stub.setattr(trade_loop.scrape_gate, 'is_regime_due', lambda *a, **k: True)
    stub.setattr(trade_loop, 'refresh_regime', lambda *a, **k: order.append('regime'))

    def _trade(*a, **k):
        order.append('trade')
        return None, set()
    stub.setattr(trade_loop, 'run_trade_only_cycle', _trade)
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    assert order == ['regime', 'trade']


def test_scraper_dispatch_failure_does_not_stop_trading(stub):
    """스크래퍼를 못 깨워도 매매는 이 워크플로의 본업이다."""
    stub.setattr(trade_loop.scrape_gate, 'is_scrape_due', lambda *a, **k: True)
    stub.setattr(trade_loop, 'dispatch_scraper',
                 mock.MagicMock(side_effect=RuntimeError('boom')))
    cycles = mock.MagicMock(return_value=(None, set()))
    stub.setattr(trade_loop, 'run_trade_only_cycle', cycles)
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    assert cycles.call_count == 1


def test_regime_refresh_failure_does_not_stop_trading(stub):
    """국면 갱신이 실패하면 직전 국면으로 매매한다 — 멈추는 것보다 낫다."""
    stub.setattr(trade_loop.scrape_gate, 'is_scrape_due', lambda *a, **k: True)
    stub.setattr(trade_loop.scrape_gate, 'is_regime_due', lambda *a, **k: True)
    stub.setattr(trade_loop, 'refresh_regime',
                 mock.MagicMock(side_effect=RuntimeError('boom')))
    cycles = mock.MagicMock(return_value=(None, set()))
    stub.setattr(trade_loop, 'run_trade_only_cycle', cycles)
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    assert cycles.call_count == 1


# ── 휴장일 ──────────────────────────────────────────────────────────

def test_holiday_stops_everything(stub):
    cycles = mock.MagicMock()
    stub.setattr(trade_loop, 'run_trade_only_cycle', cycles)
    ctx = _Ctx()
    ctx.is_trading_day = lambda: False

    trade_loop.run_trade_loop(ctx)

    cycles.assert_not_called()


def test_undecidable_trading_day_stops_everything(stub):
    """None은 개장이 아니다(2026-07-17 사고)."""
    cycles = mock.MagicMock()
    stub.setattr(trade_loop, 'run_trade_only_cycle', cycles)
    ctx = _Ctx()
    ctx.is_trading_day = lambda: None

    trade_loop.run_trade_loop(ctx)

    cycles.assert_not_called()
    assert any('판정' in m for m in ctx.logs)


# ── 배포 ────────────────────────────────────────────────────────────

def test_deploy_manifest_written_once_after_the_loop(stub, tmp_path):
    """바퀴마다 배포하면 db-data에 하루 수백 커밋이 쌓인다."""
    written = []
    stub.setattr(trade_loop, '_write_deploy_manifest',
                 lambda sim, log=print, **kw: written.append(sim))
    stub.setattr(trade_loop, 'run_trade_only_cycle',
                 mock.MagicMock(return_value=('sim4_bull_daytrading', set())))
    _budget(stub, 2)

    trade_loop.run_trade_loop(_Ctx())

    assert written == ['sim4_bull_daytrading']


def test_no_manifest_when_nothing_traded_and_regime_untouched(stub):
    written = []
    stub.setattr(trade_loop, '_write_deploy_manifest',
                 lambda sim, log=print, **kw: written.append(sim))
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock(return_value=(None, set())))
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    assert written == []


def test_regime_files_are_deployed_even_when_nothing_traded(stub):
    """이 워크플로가 국면의 유일 writer다. 매매를 안 한 사이클이라고 배포를
    건너뛰면 갱신한 국면이 db-data에 영영 도달하지 못하고, 두 워크플로가 모두
    얼어붙은 국면을 읽게 된다 — 실패가 아니라 '조용히 낡은 값으로 매매'다."""
    calls = []
    stub.setattr(trade_loop.scrape_gate, 'is_scrape_due', lambda *a, **k: True)
    stub.setattr(trade_loop.scrape_gate, 'is_regime_due', lambda *a, **k: True)
    stub.setattr(trade_loop, '_write_deploy_manifest',
                 lambda sim, log=print, include_regime=False, **kw:
                     calls.append((sim, include_regime)))
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock(return_value=(None, set())))
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    assert calls == [(None, True)]


def test_regime_files_are_not_deployed_when_refresh_failed(stub):
    """갱신에 실패했으면 올릴 새 국면이 없다 — 낡은 사본을 올리면 다른
    워크플로의 갱신을 되돌린다."""
    calls = []
    stub.setattr(trade_loop.scrape_gate, 'is_scrape_due', lambda *a, **k: True)
    stub.setattr(trade_loop.scrape_gate, 'is_regime_due', lambda *a, **k: True)
    stub.setattr(trade_loop, 'refresh_regime',
                 mock.MagicMock(side_effect=RuntimeError('boom')))
    stub.setattr(trade_loop, '_write_deploy_manifest',
                 lambda sim, log=print, include_regime=False, **kw:
                     calls.append((sim, include_regime)))
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock(return_value=(None, set())))
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    assert calls == []


def test_regime_output_files_cover_what_the_refresh_writes(tmp_path, monkeypatch):
    """국면 갱신이 건드리는 파일이 배포 목록에 다 들어 있는지 — 매니페스트에서
    파생하므로 심 이름이 바뀌어도 따라간다."""
    from src.strategy.regime_observations import month_path

    now = _Ctx().now_kst
    files = trade_loop.regime_output_files(now)
    assert os.path.basename(month_path(now)) in files
    assert any(f.endswith('_state.json') for f in files), '분석기 심 상태 파일이 있어야 한다'


def test_manifest_contains_regime_and_sim_files(tmp_path, monkeypatch):
    from src.strategy.regime_observations import month_path
    monkeypatch.chdir(tmp_path)
    now = _Ctx().now_kst
    trade_loop._write_deploy_manifest('sim4_bull_daytrading', log=lambda *a: None,
                                      now=now, include_regime=True)
    lines = (tmp_path / 'data' / '.lite_deploy_manifest').read_text(
        encoding='utf-8').split()
    assert os.path.basename(month_path(now)) in lines
    assert 'sim_bulldaytrade_state.json' in lines
    assert len(lines) == len(set(lines)), '중복 없이 기록돼야 한다'


# ── extra_sim_ids: 버즈 불필요 심 전체 배포 (2026-08-19) ────────────────
# 선택 심 하나만 올리던 매니페스트에, 60초 루프로 옮긴 나머지 버즈 불필요
# 심들(Sim2/3/4/6/8/9 등)의 상태 파일도 실려야 한다 — 안 그러면 매분 계산한
# 매매가 컨테이너 종료와 함께 증발한다.

def test_extra_sim_ids_are_included_in_the_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    trade_loop._write_deploy_manifest(
        None, log=lambda *a: None,
        extra_sim_ids={'sim_spillover', 'sim_risk'})
    lines = (tmp_path / 'data' / '.lite_deploy_manifest').read_text(
        encoding='utf-8').split()
    assert 'sim_spillover_state.json' in lines
    assert 'trade_history_sim_spillover.csv' in lines
    assert 'sim_risk_state.json' in lines


def test_sim6_extra_sim_id_also_carries_its_diag_file(tmp_path, monkeypatch):
    """심6는 이 60초 루프에서만 돌고 배포는 명시적 매니페스트로만 나가므로,
    sim_diag가 쓴 진단 CSV도 여기서 같이 실어야 db-data에 도달한다(sim1처럼
    scraper.yml에 남은 심은 그쪽 `data/*.csv` 기본 경로로 나가지만, 이 루프로
    옮겨온 sim6·sim9는 그 워크플로에서 안 돈다)."""
    from src.data.sim_diag import month_path
    monkeypatch.chdir(tmp_path)
    now = _Ctx().now_kst
    trade_loop._write_deploy_manifest(
        None, log=lambda *a: None, now=now, extra_sim_ids={'sim6_bear'})
    lines = (tmp_path / 'data' / '.lite_deploy_manifest').read_text(
        encoding='utf-8').split()
    assert 'sim_bear_state.json' in lines
    assert 'trade_history_sim_bear.csv' in lines
    assert os.path.basename(month_path('sim6', now.strftime('%Y%m%d'))) in lines


def test_sim9_extra_sim_id_also_carries_its_diag_file(tmp_path, monkeypatch):
    """2026-08-20: sim6에서 이 함정을 고친 날, 같은 60초 루프로 옮겨와 있던
    sim9도 diag를 쓰면서 똑같이 매니페스트에서 빠져 있던 게 드러났다."""
    from src.data.sim_diag import month_path
    monkeypatch.chdir(tmp_path)
    now = _Ctx().now_kst
    trade_loop._write_deploy_manifest(
        None, log=lambda *a: None, now=now, extra_sim_ids={'sim9_gap_fade'})
    lines = (tmp_path / 'data' / '.lite_deploy_manifest').read_text(
        encoding='utf-8').split()
    assert 'sim_gapfade_state.json' in lines
    assert os.path.basename(month_path('sim9', now.strftime('%Y%m%d'))) in lines


def test_both_diag_files_carried_when_both_sims_ran(tmp_path, monkeypatch):
    from src.data.sim_diag import month_path
    monkeypatch.chdir(tmp_path)
    now = _Ctx().now_kst
    trade_loop._write_deploy_manifest(
        None, log=lambda *a: None, now=now,
        extra_sim_ids={'sim6_bear', 'sim9_gap_fade'})
    lines = (tmp_path / 'data' / '.lite_deploy_manifest').read_text(
        encoding='utf-8').split()
    assert os.path.basename(month_path('sim6', now.strftime('%Y%m%d'))) in lines
    assert os.path.basename(month_path('sim9', now.strftime('%Y%m%d'))) in lines


def test_sim6_diag_file_is_skipped_without_now(tmp_path, monkeypatch):
    """now 없이 불리면(방어적 상황) 진단 파일명을 못 만드니 조용히 생략한다 —
    죽지 않는다."""
    monkeypatch.chdir(tmp_path)
    trade_loop._write_deploy_manifest(
        None, log=lambda *a: None, extra_sim_ids={'sim6_bear'})
    lines = (tmp_path / 'data' / '.lite_deploy_manifest').read_text(
        encoding='utf-8').split()
    assert 'sim_bear_state.json' in lines
    assert not any('diag' in line for line in lines)


def test_extra_sim_ids_combine_with_the_selected_sim_without_duplicating():
    """선택 심이 우연히 extra_sim_ids에도 들어 있어도(집합이라 안 그렇겠지만
    방어적으로) 파일이 두 번 적히면 안 된다."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        import os as _os
        cwd = _os.getcwd()
        _os.chdir(d)
        try:
            trade_loop._write_deploy_manifest(
                'sim4_bull_daytrading', log=lambda *a: None,
                extra_sim_ids={'sim4_bull_daytrading', 'sim_spillover'})
            lines = (open(_os.path.join(d, 'data', '.lite_deploy_manifest'),
                          encoding='utf-8').read().split())
        finally:
            _os.chdir(cwd)
    assert len(lines) == len(set(lines)), '중복 없이 기록돼야 한다'
    assert 'sim_bulldaytrade_state.json' in lines
    assert 'sim_spillover_state.json' in lines


def test_no_extra_sim_ids_behaves_like_before(tmp_path, monkeypatch):
    """extra_sim_ids를 안 주면(기본값 None) 기존 동작과 동일해야 한다."""
    monkeypatch.chdir(tmp_path)
    trade_loop._write_deploy_manifest('sim4_bull_daytrading', log=lambda *a: None)
    lines = (tmp_path / 'data' / '.lite_deploy_manifest').read_text(
        encoding='utf-8').split()
    assert lines == ['sim_bulldaytrade_state.json', 'trade_history_sim_bulldaytrade.csv']


# ── 스크래퍼 중복 dispatch 방지 ──────────────────────────────────────

def test_does_not_dispatch_while_the_scraper_is_already_running(monkeypatch):
    """스크래핑은 4분 걸리는데 이 워크플로는 2분마다 깨어난다. 게이트 상태는
    아직 갱신 전이라 '안 했다'로 보이므로, 확인 없이 부르면 중복 런이 뜬다."""
    monkeypatch.setenv('GH_PAT', 'x')
    monkeypatch.setattr(trade_loop, 'scraper_is_running', lambda log=print: True)
    post = mock.MagicMock()
    monkeypatch.setattr(trade_loop.requests, 'post', post)

    trade_loop.dispatch_scraper(log=lambda *a: None)

    post.assert_not_called()


def test_dispatches_when_the_scraper_is_idle(monkeypatch):
    monkeypatch.setenv('GH_PAT', 'x')
    monkeypatch.setattr(trade_loop, 'scraper_is_running', lambda log=print: False)
    post = mock.MagicMock(return_value=mock.MagicMock(status_code=204))
    monkeypatch.setattr(trade_loop.requests, 'post', post)

    trade_loop.dispatch_scraper(log=lambda *a: None)

    post.assert_called_once()
    assert 'scraper.yml/dispatches' in post.call_args[0][0]


# ── 주기 정합성 ─────────────────────────────────────────────────────

def test_dup_guard_is_shorter_than_the_trade_interval():
    """중복가드가 매매 주기보다 길면 바퀴가 조용히 skip되어 주기가 배로 늘어난다.

    같은 함정에 세 번 빠졌다(program_trader._DUP_GUARD_MIN 주석 참고):
      10분 주기에 가드 15분 → 실효 20분
       2분 주기에 가드 5분  → 실효 6분
      60초 주기에 가드 1.5분 → 실효 2분 (1분 매매를 만들어놓고 되돌리는 형태)
    """
    from src.pipeline.workers.program_trader import _DUP_GUARD_MIN

    assert _DUP_GUARD_MIN * 60 < trade_loop.TRADE_INTERVAL_SEC, (
        f'중복가드 {_DUP_GUARD_MIN}분이 매매 주기 '
        f'{trade_loop.TRADE_INTERVAL_SEC}초보다 길거나 같다 — 바퀴가 skip된다')


# ── 국면 게이트 분리 (2026-08-08 회귀) ───────────────────────────────
# 국면과 스크래핑은 주기가 같을 뿐 다른 일이다. 스크래핑 게이트는 스크래퍼가
# 끝나야 닫히는데 그게 4~5분 뒤라, 같이 쓰면 그 사이 trading 런들이 국면을
# 격자당 3번 갱신한다.

def test_regime_is_not_refreshed_again_while_the_scraper_is_still_running(stub):
    """스크래핑 게이트는 아직 열려 있어도(스크래퍼 미완료) 국면은 닫혀 있다."""
    stub.setattr(trade_loop.scrape_gate, 'is_scrape_due', lambda *a, **k: True)
    stub.setattr(trade_loop.scrape_gate, 'is_regime_due', lambda *a, **k: False)
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock(return_value=(None, set())))
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    trade_loop.refresh_regime.assert_not_called()
    trade_loop.dispatch_scraper.assert_called_once()


def test_marks_the_regime_gate_after_a_successful_refresh(stub):
    marks = mock.MagicMock()
    stub.setattr(trade_loop.scrape_gate, 'is_regime_due', lambda *a, **k: True)
    stub.setattr(trade_loop.scrape_gate, 'mark_regime', marks)
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock(return_value=(None, set())))
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    marks.assert_called_once()


def test_does_not_mark_the_regime_gate_when_the_refresh_failed(stub):
    """실패를 기록하면 다음 격자까지 낡은 국면으로 매매한다 — 다음 틱에 재시도."""
    marks = mock.MagicMock()
    stub.setattr(trade_loop.scrape_gate, 'is_regime_due', lambda *a, **k: True)
    stub.setattr(trade_loop.scrape_gate, 'mark_regime', marks)
    stub.setattr(trade_loop, 'refresh_regime',
                 mock.MagicMock(side_effect=RuntimeError('boom')))
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock(return_value=(None, set())))
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    marks.assert_not_called()


def test_regime_gate_file_is_deployed_with_the_regime(tmp_path, monkeypatch):
    """게이트 파일이 db-data에 안 올라가면 다음 런이 못 읽어 다시 격자당 3회로
    돌아간다 — 게이트를 만든 의미가 사라진다."""
    assert 'regime_gate_state.json' in trade_loop.regime_output_files(_Ctx().now_kst)


def test_undecidable_trading_day_alerts_a_human(stub):
    """판정 불가면 매매도 스크래핑도 안 돈다(dispatch보다 앞에서 return한다).
    그런데 이 알림은 orchestrator에만 있었다 — 스크래퍼를 깨우는 게 이 함수라,
    **정확히 그 시나리오에서 알림이 도달 불가**였다. 워크플로는 초록색이다."""
    sent = mock.MagicMock(return_value=True)
    stub.setattr(trade_loop.alerts, 'send_alert_once', sent)
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock())
    ctx = _Ctx()
    ctx.is_trading_day = lambda: None

    trade_loop.run_trade_loop(ctx)

    assert sent.call_count == 1
    assert sent.call_args[0][0] == 'holiday_check_failed'
    assert sent.call_args.kwargs['cooldown_min'] == 60


def test_the_alert_cooldown_file_is_deployed_when_the_holiday_check_fails(stub):
    """쿨다운 기록은 db-data를 왕복해야 **다음 런에** 보인다(2026-08-09).

    이 분기는 루프 끝의 매니페스트 기록보다 앞에서 return하고, 스크래퍼도
    (dispatch가 아래에 있으므로) 안 뜬다 — 여기서 안 올리면 아무도 안 올린다.
    그러면 매 런이 '첫 알림'이 되어 09:00~15:30 2분 간격 **195건**이 나간다.
    억제 없는 알림은 rate limit에 걸리거나 사람이 둔감해져서, 어느 쪽이든
    알림이 없는 것과 같다 — 이 커밋이 막으려던 바로 그 수치다.
    """
    calls = []
    # send_alert_once를 통째로 mock하지 않는다 — 쿨다운 기록이 실제로 남았는지가
    # 이 테스트의 전부다. 텔레그램 층만 갈아끼운다.
    stub.setattr(trade_loop.alerts, 'send_alert', mock.MagicMock(return_value=True))
    stub.setattr(trade_loop, '_write_deploy_manifest',
                 lambda sim, log=print, **kw: calls.append(kw))
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock())
    ctx = _Ctx()
    ctx.is_trading_day = lambda: None

    trade_loop.run_trade_loop(ctx)

    assert calls, '판정 불가 분기가 배포 목록을 아예 안 쓴다'
    assert calls[0].get('include_alerts') is True


def test_the_alert_cooldown_file_is_deployed_on_an_ordinary_run(stub):
    """휴장 분기만이 아니다(2026-08-09).

    program_prep_over_budget은 쿨다운 60분인데 매 런이 새 컨테이너다. 기록이
    db-data를 왕복하지 못하면 억제가 통째로 무력화되어 2분마다 발송된다 —
    휴장 분기에서 고쳤던 것과 정확히 같은 병이 정상 경로에 남아 있었다.
    """
    calls = []
    stub.setattr(trade_loop.alerts, 'send_alert', mock.MagicMock(return_value=True))
    stub.setattr(trade_loop, '_write_deploy_manifest',
                 lambda sim, log=print, **kw: calls.append(kw))
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock(return_value=(None, set())))
    stub.setattr(trade_loop, 'collect_rank_snapshot', lambda *a, **k: None)
    ctx = _Ctx()
    # 매매도 국면 갱신도 순위 수집도 없는 런에서 알림만 났다.
    trade_loop.alerts.send_alert_once('program_prep_over_budget', 'x', ctx.now_kst,
                                      log=lambda *a: None)

    trade_loop.run_trade_loop(ctx)

    assert calls, '알림만 난 런이 배포 목록을 아예 안 쓴다'
    assert calls[0].get('include_alerts') is True


def test_a_run_that_alerted_nothing_does_not_deploy_the_cooldown_file(stub):
    """안 바뀐 파일을 올리면, 그 사이 스크래퍼가 기록한 쿨다운을 런 시작 시점
    사본으로 되돌린다(lost update). 기록한 런만 올린다."""
    calls = []
    stub.setattr(trade_loop, '_write_deploy_manifest',
                 lambda sim, log=print, **kw: calls.append(kw))
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock(return_value=('sim4', set())))
    stub.setattr(trade_loop, 'collect_rank_snapshot', lambda *a, **k: None)
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    assert calls and calls[0].get('include_alerts') is False


def test_the_manifest_can_carry_the_alert_cooldown_file(tmp_path, monkeypatch):
    from src import alerts as alerts_mod
    monkeypatch.chdir(tmp_path)
    trade_loop._write_deploy_manifest(None, log=lambda *a: None, include_alerts=True)
    lines = (tmp_path / 'data' / '.lite_deploy_manifest').read_text(
        encoding='utf-8').split()
    assert lines == [alerts_mod.STATE_FILENAME]


def test_holiday_does_not_alert(stub):
    """휴장은 장애가 아니다. 매주 토·일에 울리면 알림이 무의미해진다."""
    sent = mock.MagicMock(return_value=True)
    stub.setattr(trade_loop.alerts, 'send_alert_once', sent)
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock())
    ctx = _Ctx()
    ctx.is_trading_day = lambda: False

    trade_loop.run_trade_loop(ctx)

    sent.assert_not_called()


# ── 국면 인계 (2026-08-08) ──────────────────────────────────────────
# 스크래퍼는 dispatch +30초쯤에 db-data를 체크아웃하는데, trade_loop가 갱신한
# 국면은 루프가 끝난 +75초에야 push된다. 즉 스크래퍼는 **정상 경로에서 항상**
# 직전 격자의 국면을 읽는다. 파일로 주고받는 한 이 순서는 못 뒤집으므로,
# 방금 계산한 값을 dispatch에 실어 보낸다.

def test_dispatch_carries_the_regime_it_just_computed(monkeypatch):
    posts = []
    monkeypatch.setattr(trade_loop, '_gh_token', lambda: 'tok')
    monkeypatch.setattr(trade_loop, 'scraper_is_running', lambda log=print: False)
    monkeypatch.setattr(trade_loop.requests, 'post',
                        lambda url, **kw: posts.append(kw) or mock.MagicMock(status_code=204))

    trade_loop.dispatch_scraper(log=lambda *a: None, regime='BULL')

    assert posts[0]['json']['inputs']['regime'] == 'BULL'


def test_dispatch_omits_the_hint_when_the_regime_is_unknown(monkeypatch):
    """모르는 값을 빈 문자열로 실어 보내면 스크래퍼가 '국면 없음'과 구분하지
    못한다. 힌트가 없으면 스크래퍼는 파일을 읽는다(한 격자 낡았지만 값은 있다)."""
    posts = []
    monkeypatch.setattr(trade_loop, '_gh_token', lambda: 'tok')
    monkeypatch.setattr(trade_loop, 'scraper_is_running', lambda log=print: False)
    monkeypatch.setattr(trade_loop.requests, 'post',
                        lambda url, **kw: posts.append(kw) or mock.MagicMock(status_code=204))

    trade_loop.dispatch_scraper(log=lambda *a: None, regime=None)

    assert 'inputs' not in posts[0]['json']


def test_the_dispatched_regime_is_the_one_just_refreshed(stub):
    """직전 격자 값이 아니라 방금 갱신한 값을 넘겨야 한다 — 그게 이 인계의 전부다."""
    stub.setattr(trade_loop.scrape_gate, 'is_scrape_due', lambda *a, **k: True)
    stub.setattr(trade_loop.scrape_gate, 'is_regime_due', lambda *a, **k: True)
    stub.setattr(trade_loop, 'refresh_regime', mock.MagicMock(return_value='SIDEWAYS'))
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock(return_value=(None, set())))
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    assert trade_loop.dispatch_scraper.call_args.kwargs['regime'] == 'SIDEWAYS'


# ── 순위 스냅샷 (2026-08-09) ────────────────────────────────────────
# 게시글 증분은 가격에 후행한다(+0.082). 열망의 본체는 돈이고, 그건 KIS 순위에
# 먼저 나타난다. 순위 API는 몇 종목을 가져오든 호출 1번인데 지금은 결과가 매번
# 버려진다 — 저장하고 빼기만 하면 추가 호출 0인 신호가 생긴다.

def test_rank_snapshot_runs_once_per_run_not_per_turn(stub):
    """수집 주기는 루프 주기와 무관한 상수여야 한다. 바퀴마다 찍으면 루프 튜닝이
    신호를 조용히 오염시키고, cycle_id 격자(120초)와도 어긋난다."""
    snap = mock.MagicMock()
    stub.setattr(trade_loop, 'collect_rank_snapshot', snap)
    stub.setattr(trade_loop, 'run_trade_only_cycle',
                 mock.MagicMock(return_value=('sim4_bull_daytrading', set())))
    _budget(stub, 3)

    trade_loop.run_trade_loop(_Ctx())

    assert snap.call_count == 1


def test_rank_snapshot_failure_does_not_stop_trading(stub):
    """페이퍼 신호 수집이 실전 매매를 막으면 안 된다."""
    stub.setattr(trade_loop, 'collect_rank_snapshot',
                 mock.MagicMock(side_effect=RuntimeError('boom')))
    cycles = mock.MagicMock(return_value=('sim4_bull_daytrading', set()))
    stub.setattr(trade_loop, 'run_trade_only_cycle', cycles)
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    assert cycles.call_count == 1


def test_rank_snapshot_happens_after_trading(stub):
    """매매가 KIS 유량을 먼저 쓴다. 순위 수집이 앞서면 주문이 유량에 밀린다."""
    order = []
    stub.setattr(trade_loop, 'collect_rank_snapshot', lambda *a, **k: order.append('rank'))

    def _trade(*a, **k):
        order.append('trade')
        return None, set()
    stub.setattr(trade_loop, 'run_trade_only_cycle', _trade)
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    assert order == ['trade', 'rank']


def test_money_files_are_deployed(tmp_path, monkeypatch):
    """직전 스냅샷이 db-data를 왕복하지 못하면 매 사이클이 warmup이 되고
    delta가 영원히 비어 신호가 통째로 사라진다."""
    names = trade_loop.money_output_files(datetime(2026, 8, 10, 10, 0))

    assert 'rank_state.json' in names
    assert 'money_2026-08.csv' in names


# ── 부분 결손 (2026-08-09) ──────────────────────────────────────────
# rank_map은 세 블록을 이어 붙인 **연결 위치**로 1부터 번호를 매긴다. 블록 하나가
# 비면 그 뒤 블록이 통째로 앞당겨져, 실제로는 가만히 있던 종목 수백 개에 블록
# 크기만 한 가짜 delta가 찍힌다. 그리고 KISDataProvider._get은 실패해도 예외
# 없이 {}를 주므로(토큰 만료·유량 초과·rt_cd≠0) 이 결손은 except로 안 잡힌다.

class _StubProvider:
    """블록별로 무엇을 돌려줄지 지정한다."""

    def __init__(self, fluctuation, foreign):
        self._fluctuation = fluctuation
        self._foreign = foreign

    def get_fluctuation_rank(self, market='0001', limit=30, **kw):
        return list(self._fluctuation.get(market, []))

    def get_foreign_institution_rank(self, limit=30, **kw):
        return list(self._foreign)


def _rows(prefix, n):
    return [{'code': f'{prefix}{i:04d}', 'name': f'종목{i}', 'price': 1000,
             'change_rate': '+1.00%', 'acml_vol': 100, 'amount': 100000}
            for i in range(n)]


def _collect_with(monkeypatch, tmp_path, provider):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'data').mkdir()
    import src.trade.kis_data_provider as kdp
    monkeypatch.setattr(kdp, 'KISDataProvider', lambda *a, **k: provider)
    logs = []
    at = trade_loop.collect_rank_snapshot(logs.append)
    return at, logs


def _money_rows(tmp_path):
    import csv as _csv
    p = next((tmp_path / 'data').glob('money_*.csv'))
    with open(p, encoding='utf-8') as f:
        return list(_csv.DictReader(f))


def test_rank_snapshot_is_skipped_when_a_block_came_back_empty(monkeypatch, tmp_path):
    """부분 스냅샷을 적느니 이 사이클을 건너뛴다 — 빈 블록은 그 블록의 delta를
    통째로 지어내게 만든다. 조회 실패를 0으로 폴백하지 않는다는 원칙과 같다."""
    provider = _StubProvider({'0001': _rows('A', 5), '1001': []}, _rows('C', 5))
    at, logs = _collect_with(monkeypatch, tmp_path, provider)

    assert at is None
    assert not (tmp_path / 'data' / 'rank_state.json').exists(), \
        '직전 스냅샷을 부분 결과로 덮어쓰면 다음 사이클의 delta까지 오염된다'
    assert any('결손' in m for m in logs), f'무엇이 비었는지 로그에 없다: {logs}'


def test_rank_snapshot_records_when_all_three_blocks_answered(monkeypatch, tmp_path):
    provider = _StubProvider({'0001': _rows('A', 5), '1001': _rows('B', 5)}, _rows('C', 5))
    at, _ = _collect_with(monkeypatch, tmp_path, provider)

    assert at is not None
    assert (tmp_path / 'data' / 'rank_state.json').exists()


def test_each_rank_api_is_its_own_source_counting_from_one(monkeypatch, tmp_path):
    """세 순위를 이어붙여 1..N을 매기면, 사이클마다 달라지는 중복 개수만큼 뒤
    블록이 밀려 가만히 있던 종목에 가짜 delta가 찍힌다(외인기관 순위의 market
    기본값이 '0001'이라 코스피 등락률과 상시 겹친다)."""
    provider = _StubProvider({'0001': _rows('A', 5), '1001': _rows('B', 5)}, _rows('C', 5))
    _collect_with(monkeypatch, tmp_path, provider)
    rows = _money_rows(tmp_path)

    assert len({r['source'] for r in rows}) == 3, '블록이 source로 갈리지 않았다'
    for src in {r['source'] for r in rows}:
        ranks = sorted(int(r['rank']) for r in rows if r['source'] == src)
        assert ranks == [1, 2, 3, 4, 5], f'{src} 순위가 1부터가 아니다: {ranks}'


def test_a_code_in_two_rank_apis_is_one_row_per_source(monkeypatch, tmp_path):
    """겹침은 정상이다. (cycle_id, source, code)가 유일해야 조인이 1:1이 된다."""
    shared = _rows('A', 3)
    provider = _StubProvider({'0001': shared, '1001': _rows('B', 3)}, shared)
    _collect_with(monkeypatch, tmp_path, provider)
    rows = _money_rows(tmp_path)

    keys = [(r['cycle_id'], r['source'], r['code']) for r in rows]
    assert len(keys) == len(set(keys)), '같은 (cycle_id, source, code)가 두 번 적혔다'
    assert len([r for r in rows if r['code'] == 'A0000']) == 2


def test_snapshot_is_stamped_at_query_time_not_run_start(monkeypatch, tmp_path):
    """조회는 런 시작보다 최대 85초 뒤다(매매 루프가 먼저 돈다). 런 시작 시각으로
    적으면 120초 격자에서 상시 한 칸 어긋나 sim_diag·1분봉과 조인되지 않는다."""
    provider = _StubProvider({'0001': _rows('A', 2), '1001': _rows('B', 2)}, _rows('C', 2))
    at, _ = _collect_with(monkeypatch, tmp_path, provider)
    rows = _money_rows(tmp_path)

    assert at.year >= 2026, '실제 조회 시각이어야 한다'
    assert rows[0]['ts'] == at.isoformat(timespec='seconds')
    assert int(rows[0]['cycle_id']) != _Ctx().cycle_id, \
        '런 시작 컨텍스트의 격자를 그대로 쓰고 있다'


def test_배포_목록이_쓰기_경로와_같은_파일을_가리킨다():
    """쓰는 파일과 올리는 파일이 갈리면 그 달 이력이 통째로 유실된다. 조용하다."""
    import datetime as _dt
    import os
    from scripts.trade_loop import regime_output_files
    from src.strategy.regime_observations import month_path

    now = _dt.datetime(2026, 9, 1, 9, 10)
    assert os.path.basename(month_path(now)) in regime_output_files(now)


def test_월이_바뀌면_배포_대상도_바뀐다():
    import datetime as _dt
    from scripts.trade_loop import regime_output_files

    aug = set(regime_output_files(_dt.datetime(2026, 8, 31, 15, 30)))
    sep = set(regime_output_files(_dt.datetime(2026, 9, 1, 9, 10)))
    assert 'regime_observations_2026-08.csv' in aug
    assert 'regime_observations_2026-09.csv' in sep
    assert 'regime_observations_2026-08.csv' not in sep


def test_국면을_올리는데_시각이_없으면_시끄럽게_실패한다(tmp_path, monkeypatch):
    """시각 없이 기본값으로 넘어가면 월 경계에서 조용히 틀린 파일을 올린다."""
    import pytest
    from scripts import trade_loop

    monkeypatch.chdir(tmp_path)
    (tmp_path / 'data').mkdir()
    with pytest.raises(ValueError):
        trade_loop._write_deploy_manifest(None, log=lambda *a: None, include_regime=True)
