"""E3 (2026-08-04 스크래퍼 지연 재설계): TradeEngineWorker.run_regime_stage().

Sim0(리베로)를 스크래핑 전에 사이클당 정확히 한 번 돌리는 진입점. 이게 성립해야
Stage 0.5의 순서 분기(needs_buzz)가 신선한 국면을 보고 판단할 수 있다.
_run_simulators()가 분석기 심(sim0_libero)을 건너뛰는 것도 같은 이유 —
사이클당 두 번 돌면 regime_history가 같은 순간을 이중 적립한다.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.trade_engine import TradeEngineWorker
from src.strategy.simulators.sim0_libero import LiberoSimulator


class _FakeCtx:
    def __init__(self):
        self.now_kst = __import__('datetime').datetime(2026, 8, 4, 11, 20)

    def is_after_market_close(self):
        return False

    def is_market_hours(self):
        return True

    def log(self, msg):
        pass


def _worker(tmp_path):
    ctx = _FakeCtx()
    w = TradeEngineWorker(ctx, storage=None)
    return w


def _libero(tmp_path):
    s = LiberoSimulator()
    s.state_file = str(tmp_path / "libero.json")
    s.csv_file = str(tmp_path / "libero.csv")
    s.log_file = str(tmp_path / "libero.log")
    s.state = {'last_run': None, 'current_regime': None}
    return s


def _bull_closes(n_rows=30, n=100):
    rows = [[100 * 1.01 ** t if i < 90 else 100 * 0.99 ** t for i in range(n)]
            for t in range(n_rows)]
    return {'dates': [f'2026-07-{t + 1:02d}' for t in range(n_rows)],
            'codes': [f'{i:06d}' for i in range(n)], 'rows': rows}


def test_run_regime_stage_returns_regime_from_live_breadth(tmp_path):
    w = _worker(tmp_path)
    sim = _libero(tmp_path)
    live = {'005930': {'price': 270000.0, 'change_rate': 1.2}}
    with mock.patch.object(w, '_fetch_top100_breadth', return_value={
             'breadth': 83.0, 'momentum': 3.5, 'sample': 100, 'codes': ['005930'], 'extra': {},
             'live': live,
         }), \
         mock.patch.object(w, '_top100_trend_from_csv', return_value=45.0), \
         mock.patch('src.strategy.simulators.sim0_libero.load_top100_closes',
                    return_value=_bull_closes()) as load, \
         mock.patch('src.strategy.registry.get_analyzer_simulator', return_value=sim), \
         mock.patch.object(w, '_append_regime_observation'):
        regime = w.run_regime_stage()
    assert regime == 'BULL'
    assert sim.state['current_regime'] == regime
    # 6단계 입력: 종가 CSV(리베로 trend와 같은 파일) + 장중 현재가
    load.assert_called_once_with('output/kospi_top100_close.csv')
    assert sim.regime6_inputs['live'] == live


def test_run_regime_stage_without_live_still_feeds_closes(tmp_path):
    """라이브 수집이 실패해도 종가 CSV는 넘긴다 — 지난 날 커밋은 종가로 해야 한다."""
    w = _worker(tmp_path)
    sim = _libero(tmp_path)
    with mock.patch.object(w, '_fetch_top100_breadth', return_value=None), \
         mock.patch('src.strategy.simulators.sim0_libero.load_top100_closes',
                    return_value=_bull_closes()), \
         mock.patch('src.strategy.registry.get_analyzer_simulator', return_value=sim), \
         mock.patch.object(w, '_append_regime_observation'):
        regime = w.run_regime_stage()
    assert regime == 'BULL'
    assert sim.regime6_inputs['live'] is None


def test_run_regime_stage_returns_none_when_analyzer_load_fails(tmp_path):
    w = _worker(tmp_path)
    with mock.patch.object(w, '_fetch_top100_breadth', return_value=None), \
         mock.patch('src.strategy.registry.get_analyzer_simulator', side_effect=ValueError('boom')):
        assert w.run_regime_stage() is None


def test_run_simulators_skips_analyzer_sim(tmp_path):
    """_run_simulators()가 sim0_libero(IS_ANALYZER)를 실행 목록에서 뺀다."""
    w = _worker(tmp_path)
    libero = _libero(tmp_path)
    other = mock.MagicMock()
    other.IS_ANALYZER = False
    other.IS_EOD = False
    other.get_universe.return_value = None
    other.state = {'portfolio': {}}

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                     return_value=[libero, other]), \
         mock.patch.object(w, '_fetch_portfolio_prices', return_value={}):
        w._run_simulators([])

    other.run.assert_called_once()
    # LiberoSimulator는 MagicMock이 아니라 실물이라 run이 불렸는지는 상태로 확인한다 —
    # 여기서는 아예 시뮬레이터 목록에서 빠졌는지가 핵심이므로 last_run이 여전히 None이어야 한다.
    assert libero.state['last_run'] is None
