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
    cycles = mock.MagicMock(return_value='sim4_bull_daytrading')
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
                 mock.MagicMock(return_value='sim4_bull_daytrading'))
    _budget(stub, 3)

    trade_loop.run_trade_loop(_Ctx())

    assert len(made) == 2, '2·3바퀴는 새 컨텍스트여야 한다(1바퀴는 인자로 받은 것)'


def test_exits_immediately_when_there_is_nothing_to_trade(stub):
    """OFF·버즈 필요 심·조회 실패는 전부 None이다. 60초를 자며 기다릴 이유가
    없다 — 재시도는 2분 뒤 태스커 하트비트가 한다."""
    cycles = mock.MagicMock(return_value=None)
    stub.setattr(trade_loop, 'run_trade_only_cycle', cycles)
    _budget(stub, 5)

    trade_loop.run_trade_loop(_Ctx())

    assert cycles.call_count == 1
    trade_loop.time.sleep.assert_not_called()


# ── 10분 격자 ───────────────────────────────────────────────────────

def test_refreshes_regime_and_wakes_scraper_only_when_due(stub):
    stub.setattr(trade_loop.scrape_gate, 'is_scrape_due', lambda *a, **k: True)
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock(return_value=None))
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    trade_loop.refresh_regime.assert_called_once()
    trade_loop.dispatch_scraper.assert_called_once()


def test_leaves_regime_and_scraper_alone_when_not_due(stub):
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock(return_value=None))
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    trade_loop.refresh_regime.assert_not_called()
    trade_loop.dispatch_scraper.assert_not_called()


def test_regime_is_refreshed_before_trading(stub):
    """매매가 국면을 읽어 소유권을 정한다 — 갱신이 뒤에 오면 이번 런 전체가
    한 사이클 낡은 국면으로 판단한다."""
    order = []
    stub.setattr(trade_loop.scrape_gate, 'is_scrape_due', lambda *a, **k: True)
    stub.setattr(trade_loop, 'refresh_regime', lambda *a, **k: order.append('regime'))
    stub.setattr(trade_loop, 'run_trade_only_cycle',
                 lambda *a, **k: order.append('trade'))
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    assert order == ['regime', 'trade']


def test_scraper_dispatch_failure_does_not_stop_trading(stub):
    """스크래퍼를 못 깨워도 매매는 이 워크플로의 본업이다."""
    stub.setattr(trade_loop.scrape_gate, 'is_scrape_due', lambda *a, **k: True)
    stub.setattr(trade_loop, 'dispatch_scraper',
                 mock.MagicMock(side_effect=RuntimeError('boom')))
    cycles = mock.MagicMock(return_value=None)
    stub.setattr(trade_loop, 'run_trade_only_cycle', cycles)
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    assert cycles.call_count == 1


def test_regime_refresh_failure_does_not_stop_trading(stub):
    """국면 갱신이 실패하면 직전 국면으로 매매한다 — 멈추는 것보다 낫다."""
    stub.setattr(trade_loop.scrape_gate, 'is_scrape_due', lambda *a, **k: True)
    stub.setattr(trade_loop, 'refresh_regime',
                 mock.MagicMock(side_effect=RuntimeError('boom')))
    cycles = mock.MagicMock(return_value=None)
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
                 lambda sim, log=print, include_regime=False: written.append(sim))
    stub.setattr(trade_loop, 'run_trade_only_cycle',
                 mock.MagicMock(return_value='sim4_bull_daytrading'))
    _budget(stub, 2)

    trade_loop.run_trade_loop(_Ctx())

    assert written == ['sim4_bull_daytrading']


def test_no_manifest_when_nothing_traded_and_regime_untouched(stub):
    written = []
    stub.setattr(trade_loop, '_write_deploy_manifest',
                 lambda sim, log=print, include_regime=False: written.append(sim))
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock(return_value=None))
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    assert written == []


def test_regime_files_are_deployed_even_when_nothing_traded(stub):
    """이 워크플로가 국면의 유일 writer다. 매매를 안 한 사이클이라고 배포를
    건너뛰면 갱신한 국면이 db-data에 영영 도달하지 못하고, 두 워크플로가 모두
    얼어붙은 국면을 읽게 된다 — 실패가 아니라 '조용히 낡은 값으로 매매'다."""
    calls = []
    stub.setattr(trade_loop.scrape_gate, 'is_scrape_due', lambda *a, **k: True)
    stub.setattr(trade_loop, '_write_deploy_manifest',
                 lambda sim, log=print, include_regime=False:
                     calls.append((sim, include_regime)))
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock(return_value=None))
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    assert calls == [(None, True)]


def test_regime_files_are_not_deployed_when_refresh_failed(stub):
    """갱신에 실패했으면 올릴 새 국면이 없다 — 낡은 사본을 올리면 다른
    워크플로의 갱신을 되돌린다."""
    calls = []
    stub.setattr(trade_loop.scrape_gate, 'is_scrape_due', lambda *a, **k: True)
    stub.setattr(trade_loop, 'refresh_regime',
                 mock.MagicMock(side_effect=RuntimeError('boom')))
    stub.setattr(trade_loop, '_write_deploy_manifest',
                 lambda sim, log=print, include_regime=False:
                     calls.append((sim, include_regime)))
    stub.setattr(trade_loop, 'run_trade_only_cycle', mock.MagicMock(return_value=None))
    _budget(stub, 1)

    trade_loop.run_trade_loop(_Ctx())

    assert calls == []


def test_regime_output_files_cover_what_the_refresh_writes(tmp_path, monkeypatch):
    """국면 갱신이 건드리는 파일이 배포 목록에 다 들어 있는지 — 매니페스트에서
    파생하므로 심 이름이 바뀌어도 따라간다."""
    from src.strategy.regime_observations import OBS_PATH_REL

    files = trade_loop.regime_output_files()
    assert os.path.basename(OBS_PATH_REL) in files
    assert any(f.endswith('_state.json') for f in files), '분석기 심 상태 파일이 있어야 한다'


def test_manifest_contains_regime_and_sim_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    trade_loop._write_deploy_manifest('sim4_bull_daytrading', log=lambda *a: None,
                                      include_regime=True)
    lines = (tmp_path / 'data' / '.lite_deploy_manifest').read_text(
        encoding='utf-8').split()
    assert 'regime_observations.csv' in lines
    assert 'sim_bulldaytrade_state.json' in lines
    assert len(lines) == len(set(lines)), '중복 없이 기록돼야 한다'


# ── 스크래퍼 중복 dispatch 방지 ──────────────────────────────────────

def test_does_not_dispatch_while_the_scraper_is_already_running(monkeypatch):
    """스크래핑은 4분 걸리는데 이 워크플로는 2분마다 깨어난다. 게이트 상태는
    아직 갱신 전이라 '안 했다'로 보이므로, 확인 없이 부르면 중복 런이 뜬다."""
    monkeypatch.setenv('GH_PAT', 'x')
    monkeypatch.setattr(trade_loop, 'scraper_is_running', lambda log=print: True)
    post = mock.MagicMock()
    monkeypatch.setattr(trade_loop.requests, 'post', post)

    trade_loop.dispatch_scraper(_Ctx(), log=lambda *a: None)

    post.assert_not_called()


def test_dispatches_when_the_scraper_is_idle(monkeypatch):
    monkeypatch.setenv('GH_PAT', 'x')
    monkeypatch.setattr(trade_loop, 'scraper_is_running', lambda log=print: False)
    post = mock.MagicMock(return_value=mock.MagicMock(status_code=204))
    monkeypatch.setattr(trade_loop.requests, 'post', post)

    trade_loop.dispatch_scraper(_Ctx(), log=lambda *a: None)

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
