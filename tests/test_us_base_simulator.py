import csv
import os
import tempfile

from src.strategy.simulators.us_base_simulator import USBaseSimulator


class _Dummy(USBaseSimulator):
    def __init__(self, data_dir, initial_cash=20000):
        self.name = 'UsDummy'
        self.initial_cash = initial_cash
        self.data_dir = data_dir
        self.state_file = os.path.join(data_dir, 'sim_usdummy_state.json')
        self.log_file = os.path.join(data_dir, 'sim_usdummy_log.json')
        self.csv_file = os.path.join(data_dir, 'trade_history_sim_usdummy.csv')
        self.load_state()


def test_fee_rates_are_zero():
    with tempfile.TemporaryDirectory() as d:
        sim = _Dummy(d)
    assert sim.BUY_FEE_RATE == 0.0
    assert sim.SELL_FEE_RATE == 0.0
    assert sim.SELL_TAX_RATE == 0.0


def test_log_trade_preserves_cents():
    with tempfile.TemporaryDirectory() as d:
        sim = _Dummy(d)
        sim.buy('AAPL', 'Apple', 45.67, 10, reason='test')
        with open(sim.csv_file, encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
    assert rows[0]['price'] == '45.67'
    assert rows[0]['total_amount'] == '456.70'


def test_buy_charges_no_fee():
    with tempfile.TemporaryDirectory() as d:
        sim = _Dummy(d, initial_cash=1000.0)
        sim.buy('AAPL', 'Apple', 45.67, 10, reason='test')
    # 수수료 0이므로 cash 차감분은 정확히 qty*price
    assert round(sim.state['cash'], 2) == round(1000.0 - 456.7, 2)
