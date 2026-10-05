"""US Sim4 — 회피형 대형주 선택.

2026-10-06 검증이 정한 모양을 지킨다: 시총 상위 풀 안에서 회피 점수로 고르고,
√시총으로 싣고, 월 1회만 바꾼다. 동일가중이나 소수 종목으로 바꾸면 2023~26년에
SPY에 연 9%p 졌던 구조로 돌아간다.
"""
import math

import pytest

from src.strategy.simulators import us_sim4_avoid as m


def _entries(n=m.BUFFER_RANK, cap=1e11):
    return {f'R{i:03d}': {'name': f'대형주{i}', 'rank': i + 1, 'score': 1 - i / 100,
                          'market_cap': cap} for i in range(n)}


def _cands(entries, price=50.0, skip=()):
    return [{'code': c, 'name': e['name'], 'rank': e['rank'], 'market_cap': e['market_cap'],
             'price': price} for c, e in entries.items() if c not in skip]


def _view(portfolio=None, nav=100_000):
    return {'portfolio': portfolio or {}, 'nav': nav, 'cash': nav, 'cooldown_codes': {}}


def _buys(o):
    return [x for x in o if x['action'] == 'BUY']


def _sells(o):
    return [x for x in o if x['action'] == 'SELL']


# ── 점수 ────────────────────────────────────────────────────────────

def test_pct_ranks_match_pandas_average_method():
    assert m._pct_ranks({'a': 1.0, 'b': 2.0, 'c': 2.0, 'd': 5.0}) == {'a': 0.25, 'b': 0.625, 'c': 0.625, 'd': 1.0}


def _row(code, cap=1e11, **sig):
    base = dict.fromkeys(m.SCORE_SIGNALS)
    base.update(sig)
    return {'code': code, 'name': code, 'market_cap': cap, **base}


def test_score_is_mean_of_signal_ranks_and_higher_is_better():
    rows = [_row('GOOD', si_dtc=-1, accr=0.05, issue=0.02, ag=-0.01, d_opm=0.03, ni_chg=0.04),
            _row('BAD', si_dtc=-9, accr=-0.05, issue=-0.2, ag=-0.5, d_opm=-0.03, ni_chg=-0.04)]
    out = m.score_pool(rows)
    assert [r['code'] for r in out] == ['GOOD', 'BAD']
    assert out[0]['score'] == 1.0 and out[1]['score'] == 0.5
    assert [r['rank'] for r in out] == [1, 2]


def test_missing_signal_is_neutral_not_worst():
    """결손을 최하위로 보면 공시 형식이 다른 회사가 이유 없이 빠진다."""
    rows = [_row('A', si_dtc=-1, accr=0.1, issue=0.1), _row('B', si_dtc=-2, accr=0.0, issue=0.0),
            _row('C', si_dtc=-3, accr=-0.1, issue=-0.1, ag=0.0, d_opm=0.0, ni_chg=0.0)]
    by = {r['code']: r for r in m.score_pool(rows)}
    # A: 세 신호 1위(1.0) + 결손 셋(0.5)
    assert by['A']['score'] == pytest.approx((1.0 * 3 + 0.5 * 3) / 6)


def test_too_few_signals_is_not_scored():
    rows = [_row('THIN', si_dtc=-1, accr=0.1), _row('OK', si_dtc=-2, accr=0.0, issue=0.0)]
    assert [r['code'] for r in m.score_pool(rows)] == ['OK']


def test_watchlist_keeps_only_buffer_rank():
    rows = [_row(f'S{i:03d}', si_dtc=-i, accr=-i, issue=-i) for i in range(120)]
    wl = m.build_watchlist(m.score_pool(rows))
    assert len(wl) == m.BUFFER_RANK and wl['S000']['rank'] == 1 and 'S100' not in wl


def test_days_to_cover_none_vs_zero():
    assert m.days_to_cover(None, 1e6) is None
    assert m.days_to_cover(5e6, None) is None
    assert m.days_to_cover(0, 1e6) == 0.0, '잔고 0주는 "모른다"가 아니다'
    assert m.days_to_cover(5e6, 1e6) == -5.0


# ── 워치리스트 저장/로드 ────────────────────────────────────────────

def test_load_is_fail_closed_on_date(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'WATCHLIST_PATH', str(tmp_path / 'w.json'))
    m.save_watchlist(_entries(3), '20261102', '202611')
    assert m.load_watchlist('20261103') == ({}, None)
    entries, month = m.load_watchlist('20261102')
    assert len(entries) == 3 and month == '202611'
    assert m.read_watchlist_file()['score_month'] == '202611'


# ── 비중 ────────────────────────────────────────────────────────────

def test_weights_follow_sqrt_market_cap_and_sum_to_one():
    codes = [f'S{i}' for i in range(40)]
    caps = {c: 1e11 for c in codes}
    caps['S0'] = 4e11
    w = m.target_weights(codes, caps)
    assert sum(w.values()) == pytest.approx(1.0)
    assert w['S0'] / w['S1'] == pytest.approx(2.0), '시총 4배면 비중은 √4 = 2배'


def test_weight_cap_binds_on_a_giant():
    """상한이 없으면 √(1e14/1e10)=100배라 혼자 72%를 먹는다. 상한 뒤 한 번만 다시
    나누므로(연구와 같은 방식) 엄밀한 10%는 아니다 — 26%까지는 갈 수 있다."""
    codes = [f'S{i}' for i in range(40)]
    caps = {c: 1e10 for c in codes}
    caps['S0'] = 1e14
    w = m.target_weights(codes, caps)
    assert w['S0'] == max(w.values()) and w['S0'] < 0.3
    assert sum(w.values()) == pytest.approx(1.0)


# ── 교체 판단 ───────────────────────────────────────────────────────

def test_first_rebalance_buys_top_forty_by_rank():
    entries = _entries()
    funnel = []
    orders, done = m.decide_us_avoid(_view(), entries, _cands(entries), {}, funnel=funnel)
    assert done
    assert {o['code'] for o in _buys(orders)} == {f'R{i:03d}' for i in range(m.MAX_HOLDINGS)}
    assert not _sells(orders)
    spent = sum(o['quantity'] * o['price'] for o in orders)
    assert 0.9 * 100_000 < spent <= 100_000 * (1 - m.CASH_RESERVE)
    assert any(f['reason'] == 'below_rank_cutoff' for f in funnel)


def test_holding_inside_buffer_is_kept_and_outside_is_sold():
    entries = _entries()
    held = {c: {'name': c, 'quantity': 49, 'avg_price': 50.0} for c in list(entries)[:39]}
    held['R070'] = {'name': 'R070', 'quantity': 49, 'avg_price': 50.0}       # 70위 — 버퍼 안
    held['GONE'] = {'name': 'GONE', 'quantity': 10, 'avg_price': 40.0}       # 감시목록 밖
    orders, done = m.decide_us_avoid(_view(held), entries, _cands(entries), {'GONE': 44.0})
    assert done
    assert [o['code'] for o in _sells(orders)] == ['GONE']
    assert _sells(orders)[0]['quantity'] is None, '이탈은 전량 매도'
    assert not _buys(orders), '40종목이 찼으면 40위(R039)를 새로 사지 않는다'


def test_sells_come_before_buys():
    entries = _entries()
    held = {'GONE': {'name': 'GONE', 'quantity': 10, 'avg_price': 40.0}}
    orders, _ = m.decide_us_avoid(_view(held), entries, _cands(entries), {'GONE': 44.0})
    assert orders[0]['action'] == 'SELL' and orders[-1]['action'] == 'BUY'


def test_incomplete_quotes_postpone_the_whole_rebalance():
    """야후가 절반만 대답한 날 '받은 것 중 상위 40'을 사면 목록이 통째로 바뀐다."""
    entries = _entries()
    skip = set(list(entries)[:20])
    funnel = []
    orders, done = m.decide_us_avoid(_view(), entries, _cands(entries, skip=skip), {}, funnel=funnel)
    assert orders == [] and done is False
    assert funnel[0]['reason'] == 'quotes_incomplete'


def test_a_few_missing_quotes_are_skipped_and_backfilled():
    entries = _entries()
    orders, done = m.decide_us_avoid(_view(), entries, _cands(entries, skip={'R000'}), {})
    codes = {o['code'] for o in _buys(orders)}
    assert done and 'R000' not in codes and 'R040' in codes and len(codes) == m.MAX_HOLDINGS


def test_unaffordable_stock_is_replaced_by_next_rank():
    entries = _entries()
    cands = _cands(entries)
    cands[0]['price'] = 9_000.0          # 균등 비중 2,450달러로는 1주도 못 산다
    funnel = []
    orders, done = m.decide_us_avoid(_view(), entries, cands, {}, funnel=funnel)
    codes = {o['code'] for o in _buys(orders)}
    assert 'R000' not in codes and 'R040' in codes and len(codes) == m.MAX_HOLDINGS
    assert any(f['code'] == 'R000' and f['reason'] == 'unaffordable' for f in funnel)


def test_small_drift_is_left_alone_and_large_drift_is_trimmed():
    entries = _entries()
    target = int(100_000 * (1 - m.CASH_RESERVE) / 40 / 50.0)     # 49주
    held = {c: {'name': c, 'quantity': target, 'avg_price': 50.0} for c in list(entries)[:40]}
    held['R001']['quantity'] = int(target * 1.1)      # 밴드 안
    held['R002']['quantity'] = target * 2             # 밴드 밖
    orders, done = m.decide_us_avoid(_view(held), entries, _cands(entries), {})
    assert done and not _buys(orders)
    assert [(o['code'], o['quantity']) for o in _sells(orders)] == [('R002', target)]


def test_held_without_quote_does_not_block_the_month():
    """상장폐지된 보유 종목은 값이 영영 안 온다. 그것 때문에 심 전체가 멈추면 안 된다."""
    entries = _entries()
    held = {'DEAD': {'name': 'DEAD', 'quantity': 10, 'avg_price': 40.0}}
    funnel = []
    orders, done = m.decide_us_avoid(_view(held), entries, _cands(entries), {}, funnel=funnel)
    assert done and len(_buys(orders)) == m.MAX_HOLDINGS and not _sells(orders)
    assert any(f['reason'] == 'exit_no_price' for f in funnel)


# ── 시뮬레이터: 한 달에 한 번만 ─────────────────────────────────────

@pytest.fixture
def sim(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'WATCHLIST_PATH', str(tmp_path / 'w.json'))
    monkeypatch.setattr(m, 'us_trading_date', lambda: '20261102')
    # 생성자를 그대로 부르면 레포의 data/에 상태 파일을 쓴다(US Sim1 테스트와 같은 우회).
    s = m.USAvoidSimulator.__new__(m.USAvoidSimulator)
    s.name = 'Us4Avoid'
    s.initial_cash = m.INITIAL_CASH
    s.data_dir = str(tmp_path)
    s.state_file = str(tmp_path / 'sim_us4avoid_state.json')
    s.log_file = str(tmp_path / 'sim_us4avoid_log.json')
    s.csv_file = str(tmp_path / 'trade_history_sim_us4avoid.csv')
    s.load_state()
    return s


def test_initial_cash_is_the_sim_specific_amount(sim):
    """다른 US 심은 2만 달러다. 40종목을 1주 단위로 √시총 비중에 맞추려면 모자란다."""
    import inspect
    assert inspect.signature(m.USAvoidSimulator.__init__).parameters['initial_cash'].default == 100_000
    assert sim.state['cash'] == 100_000


def test_rebalances_once_then_stops_asking_for_quotes(sim):
    entries = _entries()
    m.save_watchlist(entries, '20261102', '202611')
    universe = sim.get_universe()
    assert len(universe) == m.BUFFER_RANK
    prices = {c: 50.0 for c in entries}
    sim.run([dict(u, price=50.0) for u in universe], prices)
    assert len(sim.state['portfolio']) == m.MAX_HOLDINGS
    assert sim.state['rebalance_month'] == '202611'
    assert sim.get_universe() == [], '교체를 끝냈으면 감시목록 시세를 더 받을 이유가 없다'
    before = dict(sim.state['portfolio'])
    sim.run([], prices)
    assert sim.state['portfolio'] == before


def test_no_watchlist_means_no_trading_and_no_month_mark(sim):
    sim.run([], {})
    assert sim.state['portfolio'] == {} and 'rebalance_month' not in sim.state


def test_incomplete_cycle_leaves_month_open_for_retry(sim):
    entries = _entries()
    m.save_watchlist(entries, '20261102', '202611')
    sim.run([dict(u, price=50.0) for u in sim.get_universe()[:10]], {})
    assert sim.state['portfolio'] == {} and sim.state.get('rebalance_month') is None
    assert len(sim.get_universe()) == m.BUFFER_RANK


def test_next_month_rebalances_again(sim, monkeypatch):
    entries = _entries()
    m.save_watchlist(entries, '20261102', '202611')
    prices = {c: 50.0 for c in entries}
    sim.run([dict(u, price=50.0) for u in sim.get_universe()], prices)
    monkeypatch.setattr(m, 'us_trading_date', lambda: '20261201')
    shifted = {c: dict(e, rank=m.BUFFER_RANK + 1 - e['rank']) for c, e in entries.items()}
    m.save_watchlist(shifted, '20261201', '202612')
    sim.run([dict(u, price=50.0) for u in sim.get_universe()], prices)
    assert sim.state['rebalance_month'] == '202612'
    # 순위가 뒤집혀도 버퍼(80위) 안이면 그대로 든다 — 교체를 줄이는 장치다
    assert set(sim.state['portfolio']) == {f'R{i:03d}' for i in range(m.MAX_HOLDINGS)}


def test_shape_that_the_research_fixed():
    """이 숫자들이 검증된 구성이다. 바꾸려면 재생부터 다시 할 것."""
    assert (m.POOL_SIZE, m.MAX_HOLDINGS, m.BUFFER_RANK, m.WEIGHT_CAP) == (150, 40, 80, 0.10)
    assert m.SCORE_SIGNALS == ('si_dtc', 'accr', 'issue', 'ag', 'd_opm', 'ni_chg')
    assert math.isclose(m.MIN_QUOTE_COVERAGE, 0.9)
