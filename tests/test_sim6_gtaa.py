"""심6 = GTAA-KR5 상시 방어형 자산배분(관찰 심, 10-01 사용자 결정).

근거: docs/superpowers/specs/2026-10-01-bear-strategy-external-research.md §6.3(다-1).
5자산(069500·360750·148070·411060·305080) 각 20%. 월말 종가가 10개월 이동평균
(월말 종가 10개) 아래면 그 20%를 현금성 ETF로. 월 1회, 직전 완결 월말 종가로만 판정.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from src.strategy.simulators import sim6_bear_hedge as m
from src.strategy.simulators.sim6_bear_hedge import (
    ASSETS, ASSET_WEIGHT, CASH_ETF, REBALANCE_BAND, BearHedgeSimulator,
    decide_gtaa, trend_signal,
)

NAV = 3_000_000
KST = dt.timezone(dt.timedelta(hours=9))
CODES = [a['code'] for a in ASSETS]
CASH = CASH_ETF['code']


def _months_before(month, n):
    """month(YYYYMM) 직전 n개 월, 오래된→최신."""
    y, mo = int(month[:4]), int(month[4:])
    out = []
    for _ in range(n):
        mo -= 1
        if mo == 0:
            y, mo = y - 1, 12
        out.append(f'{y}{mo:02d}')
    return out[::-1]


def _hist(month_end_closes, month='202610', extra_current=True):
    """월말 종가 목록(오래된→최신, 마지막이 month 직전 달)으로 일봉 이력을 만든다.

    월마다 3개 봉. 월말 봉 앞 두 봉은 일부러 월말 종가와 다르게 둬서
    '월말 봉'이 아닌 값을 쓰면 테스트가 깨지게 한다.
    """
    rows = []
    for ym, close in zip(_months_before(month, len(month_end_closes)), month_end_closes):
        for day, px in ((3, close * 3), (15, close * 0.1), (28, close)):
            rows.append({'date': f'{ym}{day:02d}', 'close': px})
    if extra_current:
        # 이번 달 진행 중 봉은 판정에 쓰면 룩어헤드다 — 극단값으로 둔다.
        rows.append({'date': f'{month}01', 'close': 1.0})
    return rows


# ── 10개월선 신호 ─────────────────────────────────────────────────

def test_signal_above_when_last_month_end_over_sma():
    sig, _ = trend_signal(_hist([100] * 9 + [200]), '202610')
    assert sig == 'above'


def test_signal_below_when_last_month_end_under_sma():
    sig, _ = trend_signal(_hist([100] * 9 + [50]), '202610')
    assert sig == 'below'


def test_signal_boundary_equal_is_not_below():
    """'아래면 현금' — 같으면 아래가 아니다."""
    sig, _ = trend_signal(_hist([100] * 10), '202610')
    assert sig == 'above'


def test_signal_uses_only_last_ten_month_ends():
    """11개월 전 값(아주 큼)은 평균에 안 들어간다."""
    sig, _ = trend_signal(_hist([10_000] + [100] * 9 + [101]), '202610')
    assert sig == 'above'


def test_signal_ignores_current_month_bars():
    """이번 달 봉(1원)이 섞여도 판정은 직전 완결 월말만 본다(룩어헤드 금지)."""
    sig, info = trend_signal(_hist([100] * 9 + [200]), '202610')
    assert sig == 'above' and info['close'] == 200


@pytest.mark.parametrize('hist,reason', [
    ([], 'no_history'),
    (_hist([100] * 9), 'short_history'),
])
def test_signal_undeterminable(hist, reason):
    sig, info = trend_signal(hist, '202610')
    assert sig is None and info['reason'] == reason


def test_signal_stale_history_is_undeterminable():
    """직전 달(9월) 봉이 없으면 8월말 값으로 판정하지 않는다."""
    sig, info = trend_signal(_hist([100] * 10, month='202609', extra_current=False), '202610')
    assert sig is None and info['reason'] == 'stale_history'


def test_signal_month_gap_is_undeterminable():
    rows = [r for r in _hist([100] * 11) if not r['date'].startswith('202605')]
    sig, info = trend_signal(rows, '202610')
    assert sig is None and info['reason'] == 'gap_history'


# ── 비중 산출 ─────────────────────────────────────────────────────

def _view(portfolio=None, cash=NAV, nav=NAV):
    return {'portfolio': portfolio or {}, 'cash': cash, 'nav': nav,
            'initial_cash': NAV, 'cooldown_codes': {}}


def _prices(px=10_000):
    return {c: px for c in CODES + [CASH]}


def _buys(orders):
    return {o['code']: o for o in orders if o['action'] == 'BUY'}


def test_all_above_buys_each_asset_twenty_pct():
    orders = decide_gtaa(_view(), _prices(), {c: 'above' for c in CODES}, {})
    b = _buys(orders)
    assert set(b) == set(CODES)
    for o in b.values():
        assert o['quantity'] * 10_000 <= NAV * ASSET_WEIGHT
        assert o['quantity'] * 10_000 > NAV * ASSET_WEIGHT - 10_000 * 2


@pytest.mark.parametrize('k', [0, 1, 2, 5])
def test_k_below_moves_k_times_twenty_pct_to_cash_etf(k):
    sigs = {c: ('below' if i < k else 'above') for i, c in enumerate(CODES)}
    b = _buys(decide_gtaa(_view(), _prices(), sigs, {}))
    assert set(b) == set(CODES[k:]) | ({CASH} if k else set())
    if k:
        target = NAV * ASSET_WEIGHT * k
        assert target - 2 * 10_000 < b[CASH]['quantity'] * 10_000 <= target


def test_integer_quantities_and_total_within_cash():
    """비싼 단가에서 정수 절사 — 수량은 int, 총액+수수료가 현금을 넘지 않는다."""
    px = {c: 77_777 for c in CODES + [CASH]}
    orders = decide_gtaa(_view(), px, {c: 'above' for c in CODES}, {})
    spent = 0
    for o in orders:
        assert isinstance(o['quantity'], int) and o['quantity'] > 0
        spent += o['quantity'] * o['price'] * (1 + BearHedgeSimulator.BUY_FEE_RATE)
    assert spent <= NAV


def test_band_skips_small_drift():
    """목표 대비 ±5%p 미만 차이는 건드리지 않는다."""
    qty = int(NAV * (ASSET_WEIGHT + REBALANCE_BAND / 2) / 10_000)   # 22.5%
    pf = {CODES[0]: {'name': 'x', 'quantity': qty, 'avg_price': 10_000}}
    orders = decide_gtaa(_view(pf, cash=NAV - qty * 10_000), _prices(),
                         {CODES[0]: 'above'}, {})
    assert not [o for o in orders if o['code'] == CODES[0]]


def test_band_trims_large_drift():
    qty = int(NAV * 0.30 / 10_000)
    pf = {CODES[0]: {'name': 'x', 'quantity': qty, 'avg_price': 10_000}}
    orders = decide_gtaa(_view(pf, cash=NAV - qty * 10_000), _prices(),
                         {CODES[0]: 'above'}, {})
    sells = [o for o in orders if o['action'] == 'SELL' and o['code'] == CODES[0]]
    assert len(sells) == 1 and 0 < sells[0]['quantity'] < qty
    left = (qty - sells[0]['quantity']) * 10_000
    assert left >= NAV * ASSET_WEIGHT


def test_signal_flip_to_below_sells_whole_position_even_if_small():
    pf = {CODES[0]: {'name': 'x', 'quantity': 5, 'avg_price': 10_000}}
    orders = decide_gtaa(_view(pf, cash=NAV - 50_000), _prices(), {CODES[0]: 'below'}, {})
    sell = [o for o in orders if o['code'] == CODES[0]]
    assert sell and sell[0]['action'] == 'SELL' and sell[0]['quantity'] is None


def test_sells_come_before_buys_and_fund_them():
    """현금 0에서 매도 대금으로 매수한다 — 매도가 먼저여야 현금 부족이 안 난다."""
    qty = int(NAV / 10_000)
    pf = {CODES[0]: {'name': 'x', 'quantity': qty, 'avg_price': 10_000}}
    orders = decide_gtaa(_view(pf, cash=0), _prices(), {CODES[0]: 'below'}, {})
    acts = [o['action'] for o in orders]
    assert acts[0] == 'SELL' and 'BUY' in acts
    assert acts.index('BUY') > max(i for i, a in enumerate(acts) if a == 'SELL')


def test_unknown_signal_keeps_that_asset_untouched():
    """판정 불가 자산은 비중 변경 없음 — 보유분을 팔지도 더 사지도 않는다."""
    pf = {CODES[0]: {'name': 'x', 'quantity': 10, 'avg_price': 10_000}}
    sigs = {c: 'above' for c in CODES[1:]}               # CODES[0]은 판정 불가
    orders = decide_gtaa(_view(pf, cash=NAV - 100_000), _prices(), sigs, {})
    assert not [o for o in orders if o['code'] == CODES[0]]


def test_unknown_signal_keeps_its_cash_etf_slot_from_previous_month():
    """지난달 '아래'였던 자산이 이번 달 판정 불가면 그 몫의 현금성 ETF도 그대로 둔다."""
    q = int(NAV * ASSET_WEIGHT / 10_000)
    pf = {CASH: {'name': 'cd', 'quantity': q, 'avg_price': 10_000}}
    sigs = {c: 'above' for c in CODES[1:]}
    orders = decide_gtaa(_view(pf, cash=NAV - q * 10_000), _prices(), sigs,
                         {CODES[0]: 'below'})
    assert not [o for o in orders if o['code'] == CASH]


def test_missing_live_price_means_no_order_for_that_code():
    px = _prices()
    px[CODES[0]] = 0
    del px[CODES[1]]
    orders = decide_gtaa(_view(), px, {c: 'above' for c in CODES}, {})
    codes = {o['code'] for o in orders}
    assert CODES[0] not in codes and CODES[1] not in codes
    assert set(CODES[2:]) <= codes


# ── run(): 월 1회 게이트·레거시·국면 무관 ────────────────────────

def _sim(tmp_path, monkeypatch, now, history=None, trading_day=True):
    monkeypatch.setattr(m, 'log_funnel', lambda *a, **k: None)
    s = BearHedgeSimulator(initial_cash=NAV)
    s.data_dir = str(tmp_path)          # 리베로 상태 파일이 없는 디렉터리
    s.state_file = str(tmp_path / 'sim_bear_state.json')
    s.log_file = str(tmp_path / 'sim_bear_log.json')
    s.csv_file = str(tmp_path / 'trade_history_sim_bear.csv')
    s.reset_state()
    monkeypatch.setattr(m, 'get_kst_now', lambda: now)
    monkeypatch.setattr(BearHedgeSimulator, '_is_trading_day', staticmethod(lambda ymd: trading_day))
    calls = []
    hist = history if history is not None else _hist([100] * 9 + [200])

    def fetch(self, code):
        calls.append(code)
        return hist(code) if callable(hist) else list(hist)
    monkeypatch.setattr(BearHedgeSimulator, '_fetch_history', fetch)
    return s, calls


def _cands():
    return [dict(a, price=10_000) for a in ASSETS + [CASH_ETF]]


OCT1 = dt.datetime(2026, 10, 1, 9, 30, tzinfo=KST)


def test_first_run_of_month_rebalances_once(tmp_path, monkeypatch):
    s, calls = _sim(tmp_path, monkeypatch, OCT1)
    s.run(_cands(), _prices())
    assert set(s.state['portfolio']) == set(CODES)
    assert s.state['gtaa_rebalanced_month'] == '202610'
    n_trades = len(s.state['portfolio'])
    calls.clear()
    s.run(_cands(), _prices(20_000))                 # 같은 달 두 번째 런
    assert calls == []                                # 이력 조회조차 안 한다
    assert len(s.state['portfolio']) == n_trades
    assert all(p['quantity'] > 0 for p in s.state['portfolio'].values())


def test_next_month_rebalances_again(tmp_path, monkeypatch):
    s, calls = _sim(tmp_path, monkeypatch, OCT1)
    s.state['gtaa_rebalanced_month'] = '202609'
    s.run(_cands(), _prices())
    assert calls and s.state['gtaa_rebalanced_month'] == '202610'


@pytest.mark.parametrize('now,trading', [
    (dt.datetime(2026, 10, 1, 8, 30, tzinfo=KST), True),    # 개장 전
    (dt.datetime(2026, 10, 1, 15, 40, tzinfo=KST), True),   # 마감 후
    (OCT1, False),                                          # 휴장일
])
def test_no_rebalance_outside_session(tmp_path, monkeypatch, now, trading):
    s, calls = _sim(tmp_path, monkeypatch, now, trading_day=trading)
    s.run(_cands(), _prices())
    assert s.state['portfolio'] == {} and calls == []
    assert 'gtaa_rebalanced_month' not in s.state


def test_all_history_failed_does_not_consume_the_month(tmp_path, monkeypatch):
    """전부 판정 불가면 이번 달을 '했다'로 찍지 않는다 — 다음 사이클이 다시 시도."""
    s, _ = _sim(tmp_path, monkeypatch, OCT1, history=[])
    s.run(_cands(), _prices())
    assert s.state['portfolio'] == {}
    assert 'gtaa_rebalanced_month' not in s.state


def test_partial_history_failure_keeps_failed_asset(tmp_path, monkeypatch):
    good = _hist([100] * 9 + [200])
    s, _ = _sim(tmp_path, monkeypatch, OCT1,
                history=lambda code: [] if code == CODES[0] else list(good))
    s.run(_cands(), _prices())
    assert CODES[0] not in s.state['portfolio']
    assert set(CODES[1:]) <= set(s.state['portfolio'])
    assert s.state['gtaa_rebalanced_month'] == '202610'


def test_legacy_inverse_is_liquidated_on_first_run(tmp_path, monkeypatch):
    """114800(구 인버스 심 잔여)은 유니버스 밖 — 월 게이트와 무관하게 첫 런에서 청산."""
    s, _ = _sim(tmp_path, monkeypatch, dt.datetime(2026, 10, 1, 8, 0, tzinfo=KST))
    s.state['portfolio'] = {'114800': {'name': 'KODEX 인버스', 'quantity': 2852,
                                       'avg_price': 1000, 'peak_price': 1000,
                                       'entry_date': '2026-09-30', 'is_scaled_out': False}}
    s.state['cash'] = NAV - 2_852_000
    s.state['invested'] = 2_852_000
    s.run(_cands(), dict(_prices(), **{'114800': 1000}))
    assert '114800' not in s.state['portfolio']


def test_legacy_without_price_is_not_sold_at_zero(tmp_path, monkeypatch):
    s, _ = _sim(tmp_path, monkeypatch, dt.datetime(2026, 10, 1, 8, 0, tzinfo=KST))
    s.state['portfolio'] = {'114800': {'name': 'KODEX 인버스', 'quantity': 10,
                                       'avg_price': 1000, 'peak_price': 1000}}
    s.run(_cands(), _prices())
    assert s.state['portfolio']['114800']['quantity'] == 10


def test_runs_without_any_regime_state(tmp_path, monkeypatch):
    """국면 무관 — 리베로 상태 파일이 없어도 리밸런스한다(구 심6은 여기서 멈췄다)."""
    s, _ = _sim(tmp_path, monkeypatch, OCT1)
    assert not os.path.exists(tmp_path / 'sim_libero_state.json')
    s.run(_cands(), _prices())
    assert s.state['portfolio']


def test_ignores_foreign_candidates(tmp_path, monkeypatch):
    """보강 실패로 버즈 후보가 대신 들어와도 그 종목을 사지 않는다."""
    s, _ = _sim(tmp_path, monkeypatch, OCT1)
    s.run([{'code': '005930', 'name': '삼성', 'price': 70_000}],
          {'005930': 70_000, **_prices()})
    assert '005930' not in s.state['portfolio']


def test_universe_is_the_six_literal_etfs_without_price():
    """price를 안 줘야 _enrich_universe가 KIS 실시간가로 채운다(_needs_live_price)."""
    s = BearHedgeSimulator.__new__(BearHedgeSimulator)
    u = s.get_universe()
    assert [e['code'] for e in u] == CODES + [CASH]
    assert all('price' not in e for e in u)
    assert CASH not in ('459580',)
