# -*- coding: utf-8 -*-
"""국내 상장 ETF 매도에는 증권거래세가 없다 — 페이퍼 심이 그걸 반영하는지.

판별은 **명시적 코드 집합**(src/trade/fees.py의 TAX_EXEMPT_ETF_CODES)이다.
이름 접두어나 조회로 정하지 않는 이유는 fees.py 주석에 있다. 집합에 없는 코드는
모르는 것이므로 과세한다(보수 규칙) — 일반 주식을 ETF로 오판하면 세금이 빠져
성과가 부풀고, 그게 반대 방향 오판보다 위험하다.
"""
import pytest

from src.strategy.simulators.base_simulator import BaseSimulator
from src.strategy.simulators import sim6_bear_hedge as sim6
from src.trade import fees

SIM6_CODES = [a['code'] for a in sim6.ASSETS] + [sim6.CASH_ETF['code']]
LEGACY_INVERSE = ['114800', '252670']


def _sim(tmp_path, cash=3_000_000):
    sim = BaseSimulator.__new__(BaseSimulator)
    sim.name = 'T'
    sim.state_file = str(tmp_path / 'state.json')
    sim.csv_file = str(tmp_path / 'hist.csv')
    sim.state = {
        'initial_cash': cash, 'cash': cash, 'invested': 0, 'portfolio': {},
        'peak_nav': cash, 'total_fees': 0, 'history': [cash], 'daily_trades': [],
        'market_index_healthy': True, 'cooldown_codes': {},
    }
    return sim


def _hold(sim, code, name, qty, avg):
    sim.state['portfolio'][code] = {'name': name, 'quantity': qty, 'avg_price': avg,
                                    'peak_price': avg, 'is_scaled_out': False}
    sim.state['invested'] += qty * avg


# ── 판별 ──────────────────────────────────────────────────────────

@pytest.mark.parametrize('code', SIM6_CODES + LEGACY_INVERSE)
def test_known_etfs_are_tax_exempt(code):
    assert BaseSimulator.sell_tax_rate(code) == 0.0


def test_ordinary_stock_keeps_securities_tax():
    assert BaseSimulator.sell_tax_rate('005930') == fees.SELL_TAX_RATE == 0.0018


@pytest.mark.parametrize('code', [None, '', '   ', 'ABCDEF', '0695'])
def test_unknown_code_is_taxed_conservatively(code):
    """판별 불가 = 과세. 모르는 걸 면세로 두면 성과가 부푼다."""
    assert BaseSimulator.sell_tax_rate(code) == fees.SELL_TAX_RATE


def test_sim6_universe_is_registered_as_etf():
    """심6에 자산을 더하고 집합을 안 고치면 여기서 깨진다 — 조용히 과세되는 걸 막는다."""
    assert set(SIM6_CODES) <= fees.TAX_EXEMPT_ETF_CODES


def test_adm_universes_are_registered_as_etf():
    """심15·심16(듀얼모멘텀)이 사고파는 ETF도 같은 이유로 집합에 있어야 한다."""
    from src.strategy.simulators.sim15_adm import DualMomentumSimulator
    from src.strategy.simulators.sim16_adm_leveraged import LeveragedDualMomentumSimulator
    for cls in (DualMomentumSimulator, LeveragedDualMomentumSimulator):
        codes = {e['code'] for e in cls.__new__(cls).get_universe()}
        assert len(codes) == 3 and codes <= fees.TAX_EXEMPT_ETF_CODES
        assert all(BaseSimulator.sell_tax_rate(c) == 0.0 for c in codes)


# ── 페이퍼 매도 ───────────────────────────────────────────────────

def test_etf_sell_charges_commission_only(tmp_path):
    s = _sim(tmp_path, cash=0)
    _hold(s, '069500', 'KODEX 200', 100, 30_000)
    assert s.sell('069500', 31_000)
    gross = 100 * 31_000
    fee = gross * BaseSimulator.SELL_FEE_RATE
    assert s.state['cash'] == pytest.approx(gross - fee)
    assert s.state['total_fees'] == pytest.approx(fee)


def test_stock_sell_still_pays_018pct_tax(tmp_path):
    s = _sim(tmp_path, cash=0)
    _hold(s, '005930', '삼성전자', 10, 70_000)
    assert s.sell('005930', 71_000)
    gross = 10 * 71_000
    cost = gross * (BaseSimulator.SELL_FEE_RATE + BaseSimulator.SELL_TAX_RATE)
    assert s.state['cash'] == pytest.approx(gross - cost)
    assert s.state['total_fees'] == pytest.approx(cost)


def test_etf_like_name_on_unknown_code_is_still_taxed(tmp_path):
    """이름으로 판별하지 않는다 — 집합에 없는 코드는 'KODEX'가 붙어도 과세."""
    s = _sim(tmp_path, cash=0)
    _hold(s, '999999', 'KODEX 가짜', 10, 10_000)
    assert s.sell('999999', 10_000)
    gross = 100_000
    assert s.state['cash'] == pytest.approx(
        gross * (1 - BaseSimulator.SELL_FEE_RATE - BaseSimulator.SELL_TAX_RATE))


def test_legacy_inverse_sell_is_tax_exempt(tmp_path):
    s = _sim(tmp_path, cash=0)
    _hold(s, '114800', 'KODEX 인버스', 1000, 1_000)
    assert s.sell('114800', 1_000)
    assert s.state['cash'] == pytest.approx(1_000_000 * (1 - BaseSimulator.SELL_FEE_RATE))


# ── 심6 리밸런스: 계획(매도 대금 추정)과 실제 sell()이 같은 세율을 쓴다 ────

def test_sim6_rebalance_plans_with_tax_free_sell_proceeds(tmp_path):
    """매도 300주 × 10,000원 → 현금성 ETF(9,990원) 매수 수량.

    면세 대금 2,999,550 / (1+수수료) → 300주. 과세로 추정하면 299주로 1주 덜 산다.
    """
    asset = sim6.ASSETS[0]['code']
    cash_etf = sim6.CASH_ETF['code']
    pf = {asset: {'name': 'x', 'quantity': 300, 'avg_price': 10_000}}
    view = {'portfolio': pf, 'cash': 0, 'nav': 15_000_000,
            'initial_cash': 3_000_000, 'cooldown_codes': {}}
    prices = {asset: 10_000, cash_etf: 9_990}
    orders = sim6.decide_gtaa(view, prices, {asset: 'below'}, {})
    buys = [o for o in orders if o['action'] == 'BUY']
    assert [o['code'] for o in buys] == [cash_etf]
    assert buys[0]['quantity'] == 300

    # 실제로 그 순서로 실행해도 현금이 모자라지 않는다(계획 = 실행).
    s = _sim(tmp_path, cash=0)
    _hold(s, asset, 'x', 300, 10_000)
    assert s.sell(asset, 10_000)
    assert s.buy(cash_etf, sim6.CASH_ETF['name'], 9_990, 300)
    assert s.state['cash'] >= 0
