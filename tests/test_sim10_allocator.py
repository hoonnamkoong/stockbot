import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from datetime import date
from src.strategy.simulators.sim10_orchestrator import Sim10OrchestratorSimulator

# 심10의 라우팅 축은 **전일 확정 6단계**다(2026-11-24). `regime6_state.base`에서
# 라벨이 만들어지므로 그 상태를 직접 쓴다(level: -2 매우하락 / -1 하락 / 0 횡보 /
# 1 상승 / 2 매우상승, level 0은 vol10으로 약·강을 가른다).
_BASE6 = {'BULL': {'level': 1, 'vol10': 1.0},
          'BEAR': {'level': -1, 'vol10': 1.0},
          'WEAK_SIDEWAYS': {'level': 0, 'vol10': 0.5}}


def _sim(tmp_path, regime6, regime3='SIDEWAYS'):
    # Sim0 state 파일을 tmp에 두고 data_dir을 tmp로
    (tmp_path / "sim_libero_state.json").write_text(
        json.dumps({'current_regime': regime3, 'bull_score': 60.0,
                    'regime6_state': {'base': _BASE6[regime6], 'today': None}}),
        encoding='utf-8')
    s = Sim10OrchestratorSimulator(initial_cash=3_000_000)
    s.data_dir = str(tmp_path)
    s.state_file = str(tmp_path / "orch.json"); s.csv_file = str(tmp_path / "orch.csv"); s.log_file = str(tmp_path / "orch.log")
    s.state = {'initial_cash': 3_000_000, 'cash': 3_000_000, 'invested': 0, 'portfolio': {},
               'peak_nav': 3_000_000, 'total_fees': 0, 'history': [3_000_000], 'daily_trades': [],
               'market_index_healthy': True, 'cooldown_codes': {}, 'regime_log': []}
    return s


def test_bull_regime_enters_via_daytrade_logic(tmp_path):
    s = _sim(tmp_path, 'BULL')
    # 970→1100(기간변동 +13.4%, 직전 4개 종가 + 현재가 5값)에 잔파도를 줘서 ADX(37.1)를 상한(60) 아래로 유지한다
    # (2026-08-05 Sim4-1 ADX 상한 도입 — 단조상승은 ADX=100이라 이제 거부된다).
    cand = [{'code': '111', 'name': '진입주', 'price': 1100, 'amount': 5_000_000_000,
             'price_history': [{'date': f'202011{10 + i:02d}', 'close': c} for i, c in enumerate([970, 920, 1010, 950])], 'change_rate': '+3.0%',
             'orgn_fake_ntby_qty': 100, 'frgn_fake_ntby_qty': 0, 'tick_power': 130.0}]
    s.run(cand, {'111': 1100})
    assert '111' in s.state['portfolio']


def test_sideways_regime_liquidates_all(tmp_path):
    """현금 슬롯은 횡보계다(2026-11-24에 10-01의 결정을 6단계 축으로 옮겼다)."""
    s = _sim(tmp_path, 'WEAK_SIDEWAYS')
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


def test_bear_universe_is_market_cap_top100(tmp_path, monkeypatch):
    """눌림목 슬롯은 심5와 같은 중립 풀을 받아야 한다. 여기서 3단계 축이 남아
    있으면(옛 코드: BEAR → 빈 목록) 호출부가 `if not own_universe`로 **파이프라인
    버즈 후보로 폴백**해서, 라우팅을 고쳐도 눌림목이 엉뚱한 풀을 먹는다."""
    s = _sim(tmp_path, 'BEAR', regime3='BEAR')
    monkeypatch.setattr('src.data.market_cap_universe.fetch_top100',
                        lambda limit: [{'code': '005930', 'name': '삼성전자'}])
    assert [x['code'] for x in s.get_universe()] == ['005930']


def test_sideways_universe_is_empty(tmp_path):
    """현금 슬롯은 후보를 보지 않는다. 빈 목록이 파이프라인 후보로 폴백돼도 무해하다."""
    assert _sim(tmp_path, 'WEAK_SIDEWAYS').get_universe() == []


def test_universe_is_none_when_regime6_undeterminable(tmp_path):
    """판정 불가는 조회 실패와 같게 다룬다 — 지어낸 유니버스를 만들지 않는다."""
    s = _sim(tmp_path, 'BULL')
    # regime6_state를 뺀다 — 3단계는 읽히지만 라우팅 축이 없는 상태다.
    (tmp_path / "sim_libero_state.json").write_text(
        json.dumps({'current_regime': 'SIDEWAYS', 'bull_score': 60.0}), encoding='utf-8')
    assert s.get_universe() is None
