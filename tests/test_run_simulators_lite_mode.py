"""lite 경로(_run_simulators)는 네이버를 두드리지 않고, 모르는 가격을 0으로 읽지 않는다.

_run_simulators([])를 그대로 부르면 보유 종목 현재가가 전부 '미확보'로 잡혀
_fetch_portfolio_prices()가 finance.naver.com을 직접 스크래핑한다
(trade_engine.py:613-641). "스크래핑을 하지 않는다"가 전제인 2분 주기 경로에서
이게 살아 있으면 네이버를 5배 빈도로 두드리게 된다.

그리고 가격을 못 구했을 때 0을 넘기면 심은 −100% 손실로 읽고 손절을 낸다.
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.trade_engine import TradeEngineWorker


class _FakeCtx:
    now_kst = datetime(2026, 8, 6, 11, 0, tzinfo=timezone(timedelta(hours=9)))

    def is_buy_window(self):
        return True

    def is_market_hours(self):
        return True

    def should_notify(self):
        return False

    def log(self, msg):
        pass


class _FakeSim:
    IS_ANALYZER = False
    IS_EOD = False

    def __init__(self, portfolio=None, universe=None):
        self.state = {'portfolio': portfolio or {}}
        self._universe = universe
        self.ran_with = None

    def get_universe(self):
        return self._universe

    def run(self, candidates, current_prices=None):
        self.ran_with = {'candidates': candidates, 'prices': current_prices}


def _worker():
    return TradeEngineWorker(_FakeCtx(), mock.MagicMock())


def test_lite_mode_never_calls_naver_fallback():
    """보유 종목 현재가가 없어도 네이버 조회를 하지 않는다."""
    sim = _FakeSim(portfolio={'005930': {}})
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[sim]), \
         mock.patch.object(w, '_fetch_portfolio_prices') as naver:
        w._run_simulators([], allow_price_fallback=False)

    naver.assert_not_called()


def test_default_mode_still_uses_naver_fallback():
    """기존 10분 경로의 동작은 그대로다."""
    sim = _FakeSim(portfolio={'005930': {}})
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[sim]), \
         mock.patch.object(w, '_fetch_portfolio_prices', return_value={'005930': 70000}) as naver:
        w._run_simulators([])

    naver.assert_called_once()


def test_lite_mode_skips_sim_whose_holding_price_is_unknown():
    """가격을 모르면 0으로 넘기지 않고 그 심을 건너뛴다 (허위 손절 방지)."""
    sim = _FakeSim(portfolio={'005930': {}})
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[sim]):
        w._run_simulators([], allow_price_fallback=False)

    assert sim.ran_with is None, '현재가를 모르는 채로 심을 돌리면 안 된다'


def test_lite_mode_runs_sim_when_own_universe_covers_holdings():
    """자체 유니버스가 보유 종목 가격을 채워주면 정상 실행한다."""
    sim = _FakeSim(portfolio={'005930': {}},
                   universe=[{'code': '005930', 'price': 71000}])
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[sim]), \
         mock.patch.object(w, '_enrich_universe', side_effect=lambda x: x):
        w._run_simulators([], allow_price_fallback=False)

    assert sim.ran_with is not None
    assert sim.ran_with['prices']['005930'] == 71000


def test_lite_mode_runs_sim_with_no_holdings():
    """보유가 없으면 막을 이유가 없다."""
    sim = _FakeSim(portfolio={}, universe=[{'code': '000660', 'price': 200000}])
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[sim]), \
         mock.patch.object(w, '_enrich_universe', side_effect=lambda x: x):
        w._run_simulators([], allow_price_fallback=False)

    assert sim.ran_with is not None


def test_only_sim_id_runs_just_that_one():
    """lite는 실전 선택 심의 페이퍼 쌍둥이 하나만 돌린다."""
    picked = _FakeSim(universe=[{'code': '000660', 'price': 200000}])
    w = _worker()

    with mock.patch('src.strategy.registry.get_simulator_by_id',
                    return_value=picked) as by_id, \
         mock.patch('src.pipeline.workers.trade_engine.get_active_simulators') as all_sims, \
         mock.patch.object(w, '_enrich_universe', side_effect=lambda x: x):
        w._run_simulators([], only_sim_id='sim4_bull_daytrading',
                          allow_price_fallback=False)

    by_id.assert_called_once_with('sim4_bull_daytrading')
    all_sims.assert_not_called()
    assert picked.ran_with is not None


def test_only_sim_id_missing_is_not_fatal():
    """선택 심을 못 만들어도 예외로 파이프라인을 죽이지 않는다."""
    w = _worker()

    with mock.patch('src.strategy.registry.get_simulator_by_id', return_value=None):
        w._run_simulators([], only_sim_id='nonexistent_sim')
