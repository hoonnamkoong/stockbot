import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from datetime import date
from src.strategy.simulators.sim10_orchestrator import Sim10OrchestratorSimulator


def _sim(tmp_path, regime):
    # Sim0 state 파일을 tmp에 두고 data_dir을 tmp로
    (tmp_path / "sim_libero_state.json").write_text(
        json.dumps({'current_regime': regime, 'bull_score': 60.0}), encoding='utf-8')
    s = Sim10OrchestratorSimulator(initial_cash=3_000_000)
    s.data_dir = str(tmp_path)
    s.state_file = str(tmp_path / "orch.json"); s.csv_file = str(tmp_path / "orch.csv"); s.log_file = str(tmp_path / "orch.log")
    s.state = {'initial_cash': 3_000_000, 'cash': 3_000_000, 'invested': 0, 'portfolio': {},
               'peak_nav': 3_000_000, 'total_fees': 0, 'history': [3_000_000], 'daily_trades': [],
               'market_index_healthy': True, 'cooldown_codes': {}, 'regime_log': []}
    return s


def test_bull_regime_enters_via_daytrade_logic(tmp_path):
    s = _sim(tmp_path, 'BULL')
    # 90→110(기간변동 22.2%)은 유지하되 잔파도를 줘서 ADX를 상한(60) 아래로 유지한다
    # (2026-08-05 Sim4-1 ADX 상한 도입 — 단조상승은 ADX=100이라 이제 거부된다).
    cand = [{'code': '111', 'name': '진입주', 'price': 1000, 'amount': 5_000_000_000,
             'sparkline_price': [90, 97, 92, 101, 95, 110], 'change_rate': '+3.0%',
             'orgn_fake_ntby_qty': 100, 'frgn_fake_ntby_qty': 0, 'tick_power': 130.0}]
    s.run(cand, {'111': 1000})
    assert '111' in s.state['portfolio']


def test_bear_regime_liquidates_all(tmp_path):
    s = _sim(tmp_path, 'BEAR')
    s.state['portfolio'] = {'005930': {'name': '삼성', 'quantity': 10, 'avg_price': 1000,
                                       'peak_price': 1000, 'entry_date': date.today().isoformat()}}
    s.state['invested'] = 10000
    s.run([], {'005930': 1000})
    assert s.state['portfolio'] == {}


def test_bull_universe_is_fluctuation_rank(tmp_path, monkeypatch):
    s = _sim(tmp_path, 'BULL')
    called = {}
    class _FakeKIS:
        def get_fluctuation_rank(self, market, sort, limit):
            called['hit'] = True
            return [{'code': '999', 'name': 'x'}]
    monkeypatch.setattr('src.trade.kis_data_provider.KISDataProvider', lambda: _FakeKIS())
    uni = s.get_universe()
    assert called.get('hit') and uni[0]['code'] == '999'
