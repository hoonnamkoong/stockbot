"""Sim12 유니버스: KIS 등락률 상승률·하락률 각 30을 합쳐서 두 플레이북 후보를
동시에 확보한다(상승률만 보면 플레이북2용 급락 후보가 원천적으로 안 잡힌다)."""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy.simulators.sim12_regime_dual import RegimeDualSimulator


def test_universe_merges_gainers_and_decliners():
    gainers = [{'code': '111111', 'name': '상승주', 'price': 1000, 'amount': 1_000}]
    decliners = [{'code': '222222', 'name': '하락주', 'price': 900, 'amount': 900}]

    def fake_rank(market='0001', sort='0', limit=30):
        return gainers if sort == '0' else decliners

    kis = mock.MagicMock()
    kis.get_fluctuation_rank.side_effect = fake_rank
    with mock.patch('src.trade.kis_data_provider.KISDataProvider', return_value=kis):
        sim = RegimeDualSimulator(initial_cash=3_000_000)
        universe = sim.get_universe()

    codes = {s['code'] for s in universe}
    assert codes == {'111111', '222222'}


def test_universe_returns_none_on_failure():
    with mock.patch('src.trade.kis_data_provider.KISDataProvider',
                     side_effect=Exception('boom')):
        sim = RegimeDualSimulator(initial_cash=3_000_000)
        assert sim.get_universe() is None


def test_regime_none_when_libero_state_missing(tmp_path):
    sim = RegimeDualSimulator(initial_cash=3_000_000)
    sim.data_dir = str(tmp_path)  # sim_libero_state.json이 없는 빈 디렉터리
    assert sim._read_regime() is None
