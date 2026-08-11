"""final_picks는 "먼저 만난 순" 대신 fact_score·tick_power 순위 결합으로
상위 5개를 뽑는다(2026-08-11, pick_features.rank_top 배선).

Design: ~/.gstack/projects/hoonnamkoong-stockbot/Hoon_DT-main-design-20260811-222707.md
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.trade_engine import TradeEngineWorker
from src.data.schemas import StockData


@pytest.fixture(autouse=True)
def chdir_tmp(tmp_path, monkeypatch):
    """pick_features 로깅(2.5단계)이 실제 data/를 오염시키지 않도록 격리한다."""
    monkeypatch.chdir(tmp_path)


class _Ctx:
    now_kst = datetime(2026, 8, 11, 11, 0, tzinfo=timezone(timedelta(hours=9)))
    cycle_id = 12345

    def is_buy_window(self):
        return True

    def is_market_hours(self):
        return False

    def should_notify(self):
        return False

    def log(self, msg):
        pass


def _worker():
    return TradeEngineWorker(_Ctx(), mock.MagicMock())


def _sync():
    return mock.MagicMock(daily_deep_dive_codes=[], daily_reported_info=[],
                          morning_reported_info=[], afternoon_reported_info=[])


def _stock(code, fact_score, tick_power):
    return StockData(code=code, name=f'종목{code}', price=10000,
                     fact_score=fact_score, tick_power=tick_power)


def _sim_result(code, signal='BUY'):
    return {'code': code, 'name': f'종목{code}', 'signal': signal, 'reason': 'test'}


def test_picks_top_5_by_combined_rank_not_first_encountered():
    """7개 후보가 전부 BUY인데 순서상 처음 5개가 아니라, 신호가 가장 강한
    5개(A~E)가 뽑혀야 한다. F·G는 신호가 약해 순서로는 뽑혔을 종목이지만
    실제로는 밀려야 한다."""
    stocks = [
        _stock('F', fact_score=0.0, tick_power=0.0),
        _stock('G', fact_score=0.0, tick_power=0.0),
        _stock('A', fact_score=0.9, tick_power=150.0),
        _stock('B', fact_score=0.8, tick_power=140.0),
        _stock('C', fact_score=0.7, tick_power=130.0),
        _stock('D', fact_score=0.6, tick_power=120.0),
        _stock('E', fact_score=0.5, tick_power=110.0),
    ]
    sim_results = [_sim_result(s.code) for s in stocks]

    w = _worker()
    with mock.patch('src.strategy.engine.StrategyEngine') as MockEngine, \
         mock.patch.object(w, '_run_simulators'):
        MockEngine.return_value.execute_simulation.return_value = sim_results
        picks, _, _ = w.run(stocks, _sync(), skip_program_trading=True)

    assert len(picks) == 5
    assert {p['code'] for p in picks} == {'A', 'B', 'C', 'D', 'E'}
    assert [p['rank'] for p in picks] == [1, 2, 3, 4, 5]


def test_fewer_than_5_eligible_returns_all_of_them():
    stocks = [_stock('A', 0.9, 100.0), _stock('B', 0.5, 50.0)]
    sim_results = [_sim_result(s.code) for s in stocks]

    w = _worker()
    with mock.patch('src.strategy.engine.StrategyEngine') as MockEngine, \
         mock.patch.object(w, '_run_simulators'):
        MockEngine.return_value.execute_simulation.return_value = sim_results
        picks, _, _ = w.run(stocks, _sync(), skip_program_trading=True)

    assert len(picks) == 2


def test_already_deep_dived_codes_are_excluded_from_top5():
    stocks = [_stock('A', 0.9, 100.0), _stock('B', 0.8, 90.0)]
    sim_results = [_sim_result(s.code) for s in stocks]
    sync_state = _sync()
    sync_state.daily_deep_dive_codes = ['A']

    w = _worker()
    with mock.patch('src.strategy.engine.StrategyEngine') as MockEngine, \
         mock.patch.object(w, '_run_simulators'):
        MockEngine.return_value.execute_simulation.return_value = sim_results
        picks, _, _ = w.run(stocks, sync_state, skip_program_trading=True)

    assert [p['code'] for p in picks] == ['B']
