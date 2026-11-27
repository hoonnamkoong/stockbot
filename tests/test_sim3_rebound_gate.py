"""[심3] 반등 게이트(오늘 종가 > 5거래일 전 종가)는 배포 이래 한 번도 작동하지 않았다.

게이트는 `len(sparkline) >= 6`을 요구했는데 두 생산자가 sparkline_price를
`closes[:5][::-1]`, 즉 정확히 5개로 만들었다. 그래서 반등 조건은 탈락 0건으로 통과해
왔다. 여기서는 (1) ADX 입력은 예전 5값 그대로, (2) 반등은 6값으로 실제로 판정,
(3) 이력이 없으면 adx=0.0으로 메워 'adx'(전략 탈락)로 적지 않고 별도 사유로 남기는 것을 고정한다.

픽스처 여유(경계값에 얹지 않는다): 통과용 ADX 100(문턱 20), 반등 +100(+10%);
no_rebound용 ADX 100, 오늘가가 5일 전 종가보다 20(1.8%) 아래; adx용 ADX 0(문턱 20).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators import sim3_risk as mod
from src.strategy.simulators.sim3_risk import SmartRiskSimulator

NAV = 3_000_000


def _sim(tmp_path):
    s = SmartRiskSimulator(initial_cash=NAV)
    s.state_file = str(tmp_path / "s.json")
    s.csv_file = str(tmp_path / "s.csv")
    s.log_file = str(tmp_path / "s.log")
    s.state = {'initial_cash': NAV, 'cash': NAV, 'invested': 0, 'portfolio': {},
               'peak_nav': NAV, 'total_fees': 0, 'history': [NAV], 'daily_trades': [],
               'cooldown_codes': {}}
    return s


def _rows(closes):
    """날짜가 붙은 이력 계약. 전부 오늘보다 과거라 '직전 종가'로 쓰인다."""
    return [{'date': f'202011{10 + i:02d}', 'close': c} for i, c in enumerate(closes)]


def _cand(code, prior, price):
    c = {'code': code, 'name': f'종목{code}', 'price': price, 'amount': 10_000_000_000,
         'per_ttm': 1.0, 'pbr_ttm': 0.1, 'sector_name': '전기·전자'}
    if prior is not None:
        c['price_history'] = _rows(prior)
    return c


def _capture(monkeypatch):
    got = {}
    monkeypatch.setattr(mod, 'log_funnel',
                        lambda name, cands, funnel, **kw: got.__setitem__(name, funnel))
    return got


def _reasons(got):
    return [f['reason'] for f in got['Sim3']]


def test_adx_input_is_still_five_values(tmp_path, monkeypatch):
    """진입은 당일을 살린다 — 직전 4개 + 현재가 = 예전 sparkline 5값. ADX 동작은 그대로다."""
    seen = []

    def fake_adx(closes):
        seen.append(list(closes))
        return 38.0
    monkeypatch.setattr(SmartRiskSimulator, 'calculate_adx', staticmethod(fake_adx))
    sim = _sim(tmp_path)
    sim.run([_cand('111', [880, 900, 960, 920, 980], 1000)], {'111': 1000})
    assert seen == [[900, 960, 920, 980, 1000]]


def test_rebound_gate_now_rejects(tmp_path, monkeypatch):
    """5거래일 전(1100)보다 오늘(1080)이 낮다. ADX는 100이라 오직 반등 게이트만 막는다."""
    got = _capture(monkeypatch)
    sim = _sim(tmp_path)
    sim.run([_cand('111', [1100, 1000, 1020, 1040, 1060], 1080)], {'111': 1080})
    assert _reasons(got) == ['no_rebound']
    assert '111' not in sim.state['portfolio']


def test_rebound_gate_passes_when_rebounding(tmp_path, monkeypatch):
    """오늘(1100) > 5거래일 전(1000)이면 반등 게이트를 지나 매수까지 간다."""
    got = _capture(monkeypatch)
    sim = _sim(tmp_path)
    sim.run([_cand('111', [1000, 1020, 1040, 1060, 1080], 1100)], {'111': 1100})
    assert _reasons(got) == []
    assert '111' in sim.state['portfolio']


def test_weak_adx_is_still_a_strategy_rejection(tmp_path, monkeypatch):
    """이력이 있고 추세가 약하면 지금처럼 'adx'다. no_history와 섞이면 안 된다."""
    got = _capture(monkeypatch)
    sim = _sim(tmp_path)
    sim.run([_cand('111', [1000, 1000, 1020, 1000, 1020], 1000)], {'111': 1000})
    assert _reasons(got) == ['adx']


def test_new_listing_without_history_is_recorded_not_silent(tmp_path, monkeypatch):
    """못 재서 안 산 것은 'adx'(전략 탈락)가 아니라 no_history로 남고, 매수하지 않는다."""
    got = _capture(monkeypatch)
    sim = _sim(tmp_path)
    sim.run([_cand('111', None, 1000)], {'111': 1000})
    assert _reasons(got) == ['no_history']
    assert '111' not in sim.state['portfolio']


def test_short_history_is_no_history(tmp_path, monkeypatch):
    got = _capture(monkeypatch)
    sim = _sim(tmp_path)
    sim.run([_cand('111', [900, 960], 1000)], {'111': 1000})
    assert _reasons(got) == ['no_history']


def test_four_prior_closes_cannot_judge_rebound(tmp_path, monkeypatch):
    """ADX엔 4개로 충분하지만 반등엔 5개가 필요하다. 모자라면 통과시키지 않고 결손으로 남긴다."""
    got = _capture(monkeypatch)
    sim = _sim(tmp_path)
    sim.run([_cand('111', [1020, 1040, 1060, 1080], 1100)], {'111': 1100})
    assert _reasons(got) == ['no_history']
    assert '111' not in sim.state['portfolio']


def test_no_fabricated_zero_adx_in_source():
    path = os.path.join(os.path.dirname(__file__), '..', 'src', 'strategy',
                        'simulators', 'sim3_risk.py')
    src = open(path, encoding='utf-8').read()
    assert 'if sparkline else 0.0' not in src
