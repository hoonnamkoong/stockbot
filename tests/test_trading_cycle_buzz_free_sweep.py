"""run_trade_only_cycle이 선택 심 하나만이 아니라 버즈 불필요 심 전체를 매분
동기화하도록 확장(2026-08-19). Sim2/3/4/6/8/9처럼 KIS 자체 유니버스만 쓰는
심들을 10분 격자(scraper.yml)에서 60초 루프(trading.yml)로 옮기는 배선의
trading_cycle.py 쪽.

핵심 불변식:
  - 프로그램 매매가 OFF(선택 심 없음)여도 버즈 불필요 심들은 계속 돈다 —
    이들은 페이퍼일 뿐이라 실전 ON/OFF에 묶일 이유가 없다.
  - 선택 심(traded_sim_id)은 이 스윕에서 반드시 빠진다 — 이미 위에서
    universe_override로 따로 갱신했는데 여기서 또 돌리면 서로 다른
    유니버스로 두 번 갱신하는 꼴이라 파리티가 깨진다.
  - 반환된 id 집합은 trade_loop이 배포 매니페스트를 쓰는 데 쓴다 — 빠지면
    여기서 계산한 매매가 컨테이너 종료와 함께 증발한다.
"""
import os
import sys
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline import trading_cycle


class _Ctx:
    now_kst = datetime(2026, 8, 19, 11, 0)

    def __init__(self):
        self.cycle_id = 1
        self.logs = []

    def is_market_hours(self):
        return True

    def log(self, msg):
        self.logs.append(str(msg))

    def stage(self, name):
        return mock.MagicMock(__enter__=lambda s: None, __exit__=lambda s, *a: False)


def _run(traded, buzz_free_ids, worker=None):
    ctx = _Ctx()
    worker = worker or mock.MagicMock()
    with mock.patch.object(trading_cycle, 'TradeEngineWorker', return_value=worker), \
         mock.patch.object(trading_cycle, 'read_regime', return_value=('BULL', 60.0)), \
         mock.patch.object(trading_cycle, 'trade_if_buzz_free',
                           return_value=(traded, [{'code': '005930'}] if traded else None)), \
         mock.patch.object(trading_cycle, 'list_buzz_free_sim_ids',
                           return_value=buzz_free_ids):
        result = trading_cycle.run_trade_only_cycle(ctx, mock.MagicMock())
    return result, worker


def test_buzz_free_sims_run_even_when_nothing_was_traded():
    """프로그램 매매 OFF(선택 심 없음)여도 버즈 불필요 심들은 계속 돈다."""
    (traded, ran), worker = _run(None, {'sim_spillover', 'sim_risk'})

    assert traded is None
    assert ran == {'sim_spillover', 'sim_risk'}
    worker._run_simulators.assert_called_once_with(
        [], allow_price_fallback=False, include_only_sim_ids={'sim_spillover', 'sim_risk'})


def test_the_traded_sim_is_excluded_from_its_own_sweep():
    """선택 심은 위에서 이미 universe_override로 따로 갱신했다 — 여기서 또
    돌리면 다른 유니버스로 두 번 갱신해 파리티가 깨진다."""
    (traded, ran), worker = _run(
        'sim4_bull_daytrading', {'sim4_bull_daytrading', 'sim_spillover', 'sim_risk'})

    assert traded == 'sim4_bull_daytrading'
    assert ran == {'sim_spillover', 'sim_risk'}
    call = worker._run_simulators.call_args
    assert call.kwargs['include_only_sim_ids'] == {'sim_spillover', 'sim_risk'}


def test_empty_buzz_free_set_does_not_call_run_simulators_for_the_sweep():
    (traded, ran), worker = _run(None, set())

    assert ran == set()
    # 선택 심도 없고(traded=None) 버즈 불필요 집합도 비었으니 _run_simulators가
    # 아예 안 불려야 한다(선택 심 페이퍼 동기화 블록도 traded_sim_id가 없어 스킵됨).
    worker._run_simulators.assert_not_called()


def test_sweep_failure_does_not_raise():
    """버즈 불필요 스윕이 실패해도 사이클 전체가 죽으면 안 된다 — 선택 심
    매매(이미 완료됨)는 지켜야 한다."""
    worker = mock.MagicMock()
    worker._run_simulators.side_effect = RuntimeError('boom')

    (traded, ran), worker = _run('sim4_bull_daytrading', {'sim_spillover'}, worker=worker)

    assert traded == 'sim4_bull_daytrading'
    assert ran == set(), '실패했으면 배포 대상에 넣으면 안 된다'


def test_returns_a_tuple_of_traded_id_and_ran_set():
    """반환 계약이 (traded_sim_id, ran_buzz_free_ids)다 — trade_loop이 그대로 언팩한다."""
    result, _ = _run('sim4_bull_daytrading', {'sim_spillover'})
    assert isinstance(result, tuple) and len(result) == 2
    assert result[0] == 'sim4_bull_daytrading'
    assert result[1] == {'sim_spillover'}
