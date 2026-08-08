"""trade_lite(2분 주기 경로)가 하지 말아야 할 것을 하지 않는지.

이 경로의 위험은 '안 하는 것'에 있다. 국면을 갱신하면 regime_history가 5배로
부풀어 평활이 왜곡되고(하루 ~19,500 KIS 콜도 따라온다), 스크래핑을 하면
'스크래핑과 거래 분리'라는 전제 자체가 무너진다.

그리고 trade_if_buzz_free가 돌려준 sim_id를 그대로 써야 한다 — 여기서 config를
다시 조회하면, 매매 실행 중(수초~수십초) selected_sim이 바뀌었을 때 방금 매매한
심과 다른 심을(어쩌면 버즈 필요 심을) 빈 candidates로 돌리게 된다.
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts import trade_lite
from src.pipeline import orchestrator

KST = timezone(timedelta(hours=9))


class _Ctx:
    VERSION = 'test'
    today_display = '2026-08-06'

    def __init__(self, trading=True):
        self.now_kst = datetime(2026, 8, 6, 11, 0, tzinfo=KST)
        self.cycle_id = 900000
        self._trading = trading
        self.logs = []

    def is_trading_day(self):
        return self._trading

    def is_market_hours(self):
        return True

    def log(self, msg):
        self.logs.append(str(msg))

    def stage(self, name):
        return mock.MagicMock(__enter__=lambda s: None, __exit__=lambda s, *a: False)


def _run(ctx, traded_sim_id='sim4_bull_daytrading', regime='BULL', used_candidates=None):
    """traded_sim_id: trade_if_buzz_free가 돌려주는 심 id. None이면 매매 안 함.
    used_candidates: 그 매매가 실제로 쓴 후보 목록(페이퍼가 재조회 없이 물려받는다).

    매매 본체는 orchestrator.run_trade_only_cycle로 옮겨졌다(scraper.yml 오프틱
    경로와 공유 — 복사본을 두면 두 경로가 갈린다). 그래서 patch 대상이
    trade_lite가 아니라 orchestrator다. 여기서 검증하는 건 여전히
    "trade_lite를 태웠을 때의 관측 가능한 동작"이다.
    """
    with mock.patch.object(trade_lite, 'StorageManager'), \
         mock.patch.object(orchestrator, 'TradeEngineWorker') as worker_cls, \
         mock.patch.object(orchestrator, 'read_regime', return_value=(regime, 55.0)) as rr, \
         mock.patch.object(orchestrator, 'trade_if_buzz_free',
                           return_value=(traded_sim_id, used_candidates)) as tif, \
         mock.patch.object(trade_lite, '_write_deploy_manifest') as deploy:
        trade_lite.run_trade_lite(ctx)
        return worker_cls.return_value, rr, tif, deploy


def test_never_updates_regime():
    """국면 갱신(run_regime_stage)은 scraper.yml 단독 소관이다."""
    worker, read_regime_mock, _, _ = _run(_Ctx())

    worker.run_regime_stage.assert_not_called()
    read_regime_mock.assert_called_once()


def test_passes_read_regime_value_into_buzz_branch():
    """읽어온 국면이 needs_buzz(dynamic) 판단에 그대로 들어가야 한다 (Sim10)."""
    ctx = _Ctx()
    _, _, tif, _ = _run(ctx, regime='SIDEWAYS')

    assert tif.call_args[0][2] == 'SIDEWAYS'


def test_syncs_only_the_sim_that_trade_if_buzz_free_returned():
    """페이퍼 갱신 대상은 trade_if_buzz_free의 반환값 그대로다.

    다른 곳에서 selected_sim을 다시 조회하면 안 된다(레이스 — 위 모듈 docstring).
    """
    worker, _, _, deploy = _run(_Ctx(), traded_sim_id='sim4_bull_daytrading')

    worker._run_simulators.assert_called_once()
    args, kwargs = worker._run_simulators.call_args
    assert kwargs['only_sim_id'] == 'sim4_bull_daytrading'
    assert kwargs['allow_price_fallback'] is False
    deploy.assert_called_once_with('sim4_bull_daytrading', mock.ANY)


def test_paper_twin_reuses_the_universe_the_real_trade_used():
    """페이퍼 쌍둥이는 실전이 쓴 그 후보 목록으로 돌아야 한다.

    여기서 get_universe()를 다시 부르면 수십 초 뒤의 라이브 랭킹이라 다른
    '당일 등락률 상위 30'이 나올 수 있고, 그러면 실전과 페이퍼가 서로 다른
    입력으로 판단한다 — "심 선택 = 실전 정확히 동일 동작"이 깨진다.
    """
    used = [{'code': '005930', 'price': 70000}]
    worker, _, _, _ = _run(_Ctx(), used_candidates=used)

    assert worker._run_simulators.call_args.kwargs['universe_override'] is used


def test_does_not_requery_selected_sim_after_trading():
    """trade_if_buzz_free가 반환한 값 외에는 심 선택을 다시 조회하지 않는다.

    peek_selected_sim을 trade_lite 모듈에서 직접 부르지 않아야 한다 — 여기 다시
    부르면, 매매 실행 중 config의 selected_sim이 바뀌었을 때 방금 매매한 심과
    다른 심의 페이퍼를(어쩌면 버즈 필요 심을 빈 candidates로) 돌리게 된다.
    """
    assert not hasattr(trade_lite, 'peek_selected_sim'), (
        'trade_lite가 peek_selected_sim을 다시 import하면 안 된다 — '
        'trade_if_buzz_free의 반환값만 써야 한다')


def test_no_paper_sync_when_it_did_not_trade():
    """버즈 필요 심이 선택돼 이 경로가 매매하지 않았으면 페이퍼도 건드리지 않는다.

    그 심은 scraper.yml이 10분 주기로 매매·갱신한다.
    """
    worker, _, _, deploy = _run(_Ctx(), traded_sim_id=None)

    worker._run_simulators.assert_not_called()
    deploy.assert_not_called()


def test_stops_on_holiday():
    ctx = _Ctx(trading=False)
    worker, _, tif, _ = _run(ctx)

    tif.assert_not_called()
    assert any('휴장' in m for m in ctx.logs)


def test_stops_when_holiday_check_is_inconclusive():
    """판정 불가는 개장이 아니다 — fail-closed."""
    ctx = _Ctx(trading=None)
    worker, _, tif, _ = _run(ctx)

    tif.assert_not_called()
    assert any('판정할 수 없' in m for m in ctx.logs)


def test_deploy_manifest_lists_only_the_synced_sim(tmp_path, monkeypatch):
    """배포 목록에는 이번 런이 실제로 쓴 파일만 들어간다.

    '바뀐 파일 전부'로 하면 런 시작 시점에 받아온 다른 심의 낡은 사본까지 올려
    스크래퍼의 갱신을 되돌린다.
    """
    monkeypatch.chdir(tmp_path)
    registry = [
        {'id': 'sim4_bull_daytrading', 'state_file': 'sim_bulldaytrade_state.json',
         'csv_file': 'trade_history_sim_bulldaytrade.csv'},
        {'id': 'sim6_bear', 'state_file': 'sim_bear_state.json',
         'csv_file': 'trade_history_sim_bear.csv'},
    ]

    with mock.patch('src.strategy.registry.get_sim_registry', return_value=registry):
        trade_lite._write_deploy_manifest('sim4_bull_daytrading', log=lambda *a: None)

    written = (tmp_path / 'data' / '.lite_deploy_manifest').read_text(encoding='utf-8').split()
    assert written == ['sim_bulldaytrade_state.json', 'trade_history_sim_bulldaytrade.csv']
    assert not any('bear' in w for w in written), '안 건드린 심은 배포 목록에 없어야 한다'


def test_no_deploy_manifest_when_sim_is_unknown(tmp_path, monkeypatch):
    """레지스트리에 없는 심이면 목록을 만들지 않는다 — 배포 스텝이 통째로 생략된다."""
    monkeypatch.chdir(tmp_path)

    with mock.patch('src.strategy.registry.get_sim_registry', return_value=[]):
        trade_lite._write_deploy_manifest('ghost_sim', log=lambda *a: None)

    assert not (tmp_path / 'data' / '.lite_deploy_manifest').exists()


def test_paper_sync_failure_does_not_break_the_run():
    """페이퍼 동기화는 부가 작업이다 — 실패해도 이미 나간 매매를 되돌리지 않는다."""
    ctx = _Ctx()
    with mock.patch.object(trade_lite, 'StorageManager'), \
         mock.patch.object(orchestrator, 'TradeEngineWorker') as worker_cls, \
         mock.patch.object(orchestrator, 'read_regime', return_value=('BULL', 55.0)), \
         mock.patch.object(orchestrator, 'trade_if_buzz_free',
                           return_value=('sim4_bull_daytrading', None)):
        worker_cls.return_value._run_simulators.side_effect = RuntimeError('boom')
        trade_lite.run_trade_lite(ctx)

    assert any('페이퍼 동기화 실패' in m for m in ctx.logs)
