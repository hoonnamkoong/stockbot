"""오프틱 사이클에서 유니버스를 한 번만 조회한다.

2026-08-08 점검에서 나온 문제: 한 오프틱 사이클이 유니버스를 두 번 만들었다.
  1) run_program_trading → _resolve_candidates → sim.get_universe() + enrich(30종목)
  2) 곧이어 페이퍼 동기화 → _run_simulators → sim.get_universe() + enrich(30종목)

부하도 문제지만(네이버 30페이지 × 2 × 약 150사이클/일), 더 큰 건 파리티다.
두 조회는 수십 초 차이라 서로 다른 '당일 등락률 상위 30'을 볼 수 있고, 그러면
실전과 그 페이퍼 쌍둥이가 **다른 유니버스로 판단**한다. "심 선택 = 실전 정확히
동일 동작"이 무너지는 방식이다.
"""
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.workers import trade_engine


class _Sim:
    """유니버스를 부를 때마다 다른 결과를 주는 심(라이브 랭킹을 흉내낸다)."""

    IS_ANALYZER = False
    IS_EOD = False

    def __init__(self):
        self.calls = 0
        self.state = {'portfolio': {}}
        self.ran_with = None

    def get_universe(self):
        self.calls += 1
        return [{'code': f'00{self.calls}', 'price': 1000 * self.calls}]

    def run(self, candidates, current_prices=None):
        self.ran_with = candidates


@pytest.fixture
def worker(monkeypatch):
    w = trade_engine.TradeEngineWorker.__new__(trade_engine.TradeEngineWorker)
    w.log = lambda *a, **k: None
    w.log_error = lambda *a, **k: None
    w._enrich_universe = lambda stocks: [dict(s, enriched=True) for s in stocks]
    return w


def test_universe_override_skips_refetch(worker, monkeypatch):
    sim = _Sim()
    monkeypatch.setattr('src.strategy.registry.get_simulator_by_id', lambda *a, **k: sim)

    already = [{'code': '005930', 'price': 70000, 'enriched': True}]
    worker._run_simulators([], only_sim_id='sim4_bull_daytrading',
                           allow_price_fallback=False, universe_override=already)

    assert sim.calls == 0, "override를 줬는데 유니버스를 다시 조회했다"
    assert sim.ran_with == already


def test_without_override_the_sim_resolves_its_own_universe(worker, monkeypatch):
    """override가 없으면 기존 동작 그대로다(스크래핑 경로가 이 길을 쓴다)."""
    sim = _Sim()
    monkeypatch.setattr('src.strategy.registry.get_simulator_by_id', lambda *a, **k: sim)

    worker._run_simulators([], only_sim_id='sim4_bull_daytrading',
                           allow_price_fallback=False)

    assert sim.calls == 1
    assert sim.ran_with[0]['enriched'] is True


def test_empty_override_is_not_treated_as_a_universe(worker, monkeypatch):
    """빈 리스트는 '유니버스가 비었다'가 아니라 '넘겨받은 게 없다'로 읽는다 —
    프로그램 매매가 후보를 못 만든 사이클에 페이퍼가 빈 유니버스로 돌면
    보유 종목 현재가가 통째로 사라져 허위 손절이 난다."""
    sim = _Sim()
    monkeypatch.setattr('src.strategy.registry.get_simulator_by_id', lambda *a, **k: sim)

    worker._run_simulators([], only_sim_id='sim4_bull_daytrading',
                           allow_price_fallback=False, universe_override=[])

    assert sim.calls == 1


def test_program_trading_returns_the_universe_it_actually_used(monkeypatch):
    """run_program_trading이 자기가 확정한 후보를 호출부에 돌려줘야
    페이퍼 쪽이 재조회 없이 같은 스냅샷을 쓸 수 있다."""
    from unittest import mock
    from src.pipeline.workers import program_trader as pt

    sim = _Sim()
    ledger = {'positions': {}, 'last_run': None, 'sim': None, 'realized_pnl': 0,
              'cooldown_codes': {}, 'turn': {}, 'lock_run_id': None, 'lock_at': None}

    with mock.patch.object(pt, '_read_config_fresh', return_value={
             'enabled': True, 'selected_sim': 'sim4_bull_daytrading', 'budget': 2_000_000}), \
         mock.patch.object(pt, '_read_ledger_fresh', return_value=(ledger, 'sha-1')), \
         mock.patch.object(pt, '_write_ledger', return_value=(True, 'sha-2')), \
         mock.patch('src.trade.balance.get_balance',
                    return_value={'deposit': 2_000_000, 'holdings': []}), \
         mock.patch('src.strategy.registry.get_tradeable_simulator_ids',
                    return_value=['sim4_bull_daytrading']), \
         mock.patch('src.strategy.registry.get_simulator_by_id', return_value=sim), \
         mock.patch.object(pt, '_make_adapter', return_value=[]):
        used = pt.run_program_trading(
            [], is_market_hours=True, now_kst=datetime(2026, 8, 10, 10, 30),
            log=lambda *a: None, log_error=lambda *a: None,
            enrich=lambda stocks: [dict(s, enriched=True) for s in stocks])

    assert sim.calls == 1, "프로그램 경로가 유니버스를 정확히 한 번 조회해야 한다"
    assert used == [{'code': '001', 'price': 1000, 'enriched': True}]


def test_program_trading_returns_none_when_it_did_not_trade(monkeypatch):
    """OFF면 돌려줄 유니버스가 없다 — 호출부는 이걸로 페이퍼 동기화 여부를 정한다."""
    from unittest import mock
    from src.pipeline.workers import program_trader as pt

    with mock.patch.object(pt, '_read_config_fresh', return_value=None):
        assert pt.run_program_trading(
            [], is_market_hours=True, now_kst=datetime(2026, 8, 10, 10, 30),
            log=lambda *a: None, log_error=lambda *a: None) is None
