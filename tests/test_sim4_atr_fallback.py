"""[심4] ATR 손절·진입 ADX가 상수/0.0으로 메워지지 않는지 고정한다.

청산 루프는 보유 종목을 '그날 후보 목록'에서만 찾았고 심4의 유니버스는 당일 상승률
상위 30개라, 손실 종목은 구조적으로 후보에 없다 → sparkline이 비어 atr_pct=3.0(-9%
고정 손절)이 걸렸다. 진입 쪽은 같은 결손이 adx=0.0이 되어 'adx_low'(전략 탈락)로
기록돼 '추세가 약해 안 샀다'와 '못 재서 안 샀다'가 한 줄이 됐다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators import sim4_bull_momentum as mod
from src.strategy.simulators.sim4_bull_momentum import BullMomentumSimulator

NAV = 3_000_000


def _sim(tmp_path, portfolio=None):
    s = BullMomentumSimulator(initial_cash=NAV)
    s.state_file = str(tmp_path / "s.json")
    s.csv_file = str(tmp_path / "s.csv")
    s.log_file = str(tmp_path / "s.log")
    s.state = {'initial_cash': NAV, 'cash': NAV, 'invested': 0, 'portfolio': portfolio or {},
               'peak_nav': NAV, 'total_fees': 0, 'history': [NAV], 'daily_trades': [],
               'cooldown_codes': {}}
    return s


def _held(*codes, avg=1000):
    return {c: {'name': c, 'quantity': 10, 'avg_price': avg, 'peak_price': avg} for c in codes}


def _rows(closes):
    """날짜가 붙은 이력 계약. 전부 오늘보다 과거라 '직전 종가'로 쓰인다."""
    return [{'date': f'202011{10 + i:02d}', 'close': c} for i, c in enumerate(closes)]


# ── 청산 ────────────────────────────────────────────────────────

def test_no_atr_stop_without_history(tmp_path, capsys):
    """이력이 없으면 ATR 손절을 내지 않는다 — -9% 상수로 메우지 않는다. 건너뜀은 로그에 남는다."""
    sim = _sim(tmp_path, _held('H1'))
    sim.run([], {'H1': 850})  # -15%: 예전엔 -9% 상수 손절이 났다
    assert 'H1' in sim.state['portfolio']
    assert 'H1' in capsys.readouterr().out


def test_trailing_stop_still_fires_without_history(tmp_path):
    """이력이 없어도 트레일링은 peak_price만으로 판정되어 계속 난다(이때 유일한 방어선)."""
    pf = _held('H1')
    pf['H1']['peak_price'] = 1100
    sim = _sim(tmp_path, pf)
    sim.run([], {'H1': 1040})  # 고점 -5.5%, 활성화(+5%) 이후
    assert 'H1' not in sim.state['portfolio']


def test_atr_stop_uses_supplied_history(tmp_path):
    """후보엔 없고 공급 이력만 있어도 ATR 손절이 난다. ATR 20 → 손절선 -6%(상수 -9%면 안 난다)."""
    sim = _sim(tmp_path, _held('H1'))
    sim.price_history = {'H1': _rows([1000, 1020, 1000, 1020, 1000])}
    sim.run([], {'H1': 930})  # -7%
    assert 'H1' not in sim.state['portfolio']


def test_stop_differs_by_stock(tmp_path):
    """같은 진입가·같은 현재가(-8%)인데 변동성이 다르면 판정이 갈린다. 상수였다면 둘 다 같다."""
    sim = _sim(tmp_path, _held('CALM', 'WILD'))
    sim.price_history = {'CALM': _rows([1000, 1020, 1000, 1020, 1000]),   # ATR 20 → -6%
                         'WILD': _rows([1000, 1060, 1000, 1060, 1000])}   # ATR 60 → -18%
    sim.run([], {'CALM': 920, 'WILD': 920})
    assert 'CALM' not in sim.state['portfolio']
    assert 'WILD' in sim.state['portfolio']


def test_future_dated_row_does_not_feed_exit_atr(tmp_path):
    """오늘 이후 날짜 행은 직전 종가가 아니다. 그 행을 빼면 5개가 안 돼 측정 불가가 된다."""
    sim = _sim(tmp_path, _held('H1'))
    rows = _rows([1000, 1020, 1000, 1020])
    rows.append({'date': '20991231', 'close': 1000})
    sim.price_history = {'H1': rows}
    sim.run([], {'H1': 930})
    assert 'H1' in sim.state['portfolio']


def test_no_constant_fallback_literal_in_source():
    path = os.path.join(os.path.dirname(__file__), '..', 'src', 'strategy',
                        'simulators', 'sim4_bull_momentum.py')
    src = open(path, encoding='utf-8').read()
    assert 'atr_pct = 3.0' not in src
    assert 'sparkline_price' not in src


# ── 진입 ────────────────────────────────────────────────────────

def _cand(code, hist_closes, price=1000):
    c = {'code': code, 'name': f'종목{code}', 'price': price, 'amount': 5_000_000_000,
         'change_rate': '+3.0%', 'orgn_fake_ntby_qty': 100, 'frgn_fake_ntby_qty': 0,
         'tick_power': 130.0}
    if hist_closes is not None:
        c['price_history'] = _rows(hist_closes)
    return c


def _capture_funnel(monkeypatch):
    got = {}
    monkeypatch.setattr(mod, 'log_funnel',
                        lambda name, cands, funnel, buys=0: got.__setitem__(name, funnel))
    return got


def test_entry_adx_input_is_prior_four_plus_current(tmp_path, monkeypatch):
    """진입 ADX 입력은 직전 4개 종가 + 현재가 = 예전과 같은 5개. 당일 제외는 청산에만 적용한다."""
    seen = []

    def fake_adx(closes):
        seen.append(list(closes))
        return 38.0
    monkeypatch.setattr(BullMomentumSimulator, 'calculate_adx', staticmethod(fake_adx))
    sim = _sim(tmp_path)
    sim.run([_cand('111', [900, 960, 920, 980])], {'111': 1000})
    assert seen == [[900, 960, 920, 980, 1000]]


def test_entry_buys_with_supplied_history(tmp_path):
    sim = _sim(tmp_path)
    sim.run([_cand('111', [900, 960, 920, 980])], {'111': 1000})  # ADX≈55.6, 기간 +11%
    assert '111' in sim.state['portfolio']


def test_entry_without_history_is_no_history_not_adx_low(tmp_path, monkeypatch):
    """못 재서 안 산 것은 'adx_low'(전략 탈락)가 아니라 별도 사유로 남고, 매수하지 않는다."""
    got = _capture_funnel(monkeypatch)
    sim = _sim(tmp_path)
    sim.run([_cand('111', None)], {'111': 1000})
    reasons = [f['reason'] for f in got['상승모멘텀']]
    assert reasons == ['no_history']
    assert '111' not in sim.state['portfolio']


def test_entry_short_history_is_no_history(tmp_path, monkeypatch):
    got = _capture_funnel(monkeypatch)
    sim = _sim(tmp_path)
    sim.run([_cand('111', [900, 960])], {'111': 1000})
    assert [f['reason'] for f in got['상승모멘텀']] == ['no_history']
