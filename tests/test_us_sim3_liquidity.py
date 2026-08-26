"""US Sim3 — 유동성 상위 보유(기준선 심).

이 심은 알파를 노리지 않는다. 2025-01~2026-08 20개월 검증에서 후보 22종이 전부
"거래대금 상위를 그냥 들고 있기"를 못 이겼고(전략 최고 +14.6% vs 기준선 +39.4%),
그래서 이걸 **잣대**로 세운다. 그러므로 테스트도 "신호를 만들지 않는다"를 지킨다 —
랭킹 외의 어떤 조건도 진입에 끼어들면 안 된다.
"""
from src.strategy.simulators import us_sim3_liquidity as m


def _entries(n=8, base=1_000_000_000.0):
    """거래대금 내림차순 워치리스트. R000이 1위."""
    return {
        f'R{i:03d}': {'name': f'유동주{i}', 'avg_dollar_volume': base - i * 1_000_000.0}
        for i in range(n)
    }


def _cands(entries, price=100.0):
    return [{'code': c, 'name': e['name'], 'price': price,
             'avg_dollar_volume': e['avg_dollar_volume']}
            for c, e in entries.items()]


def _view(portfolio, nav=20000, cash=20000):
    return {'portfolio': portfolio, 'nav': nav, 'cash': cash, 'cooldown_codes': {}}


def _buys(o):
    return [x for x in o if x['action'] == 'BUY']


def _sells(o):
    return [x for x in o if x['action'] == 'SELL']


# ── 워치리스트 구성 ──────────────────────────────────────────
def test_build_watchlist_keeps_only_top_n_by_dollar_volume():
    rows = [(f'S{i:03d}', f'이름{i}', float(i)) for i in range(50)]
    wl = m.build_watchlist(rows)
    assert len(wl) == m.TOP_N
    # 거래대금이 가장 큰 TOP_N개만 남는다
    assert set(wl) == {f'S{i:03d}' for i in range(50 - m.TOP_N, 50)}


def test_build_watchlist_drops_missing_or_nonpositive_volume():
    rows = [('A', 'A사', 5.0), ('B', 'B사', 0.0), ('C', 'C사', None), ('D', 'D사', 3.0)]
    wl = m.build_watchlist(rows)
    assert set(wl) == {'A', 'D'}


def test_build_watchlist_records_rank():
    rows = [('A', 'A사', 10.0), ('B', 'B사', 30.0), ('C', 'C사', 20.0)]
    wl = m.build_watchlist(rows)
    assert wl['B']['rank'] == 1
    assert wl['C']['rank'] == 2
    assert wl['A']['rank'] == 3


# ── 워치리스트 저장/로드는 날짜 게이트 ──────────────────────
def test_watchlist_roundtrip_and_date_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'WATCHLIST_PATH', str(tmp_path / 'wl.json'))
    m.save_watchlist(_entries(3), '20260825')
    assert set(m.load_watchlist('20260825')) == {'R000', 'R001', 'R002'}
    # 날짜가 다르면 fail-closed
    assert m.load_watchlist('20260826') == {}


def test_load_watchlist_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'WATCHLIST_PATH', str(tmp_path / 'none.json'))
    assert m.load_watchlist('20260825') == {}


# ── 리밸런스 주기 ────────────────────────────────────────────
def test_first_run_rebalances_immediately():
    o = m.decide_us_liquidity(_view({}), _cands(_entries()), {}, sched={})
    assert len(_buys(o)) == m.MAX_HOLDINGS


def test_no_rebalance_before_interval_elapsed():
    sched = {'elapsed': m.REBALANCE_DAYS - 1, 'last_seen': '20260825'}
    o = m.decide_us_liquidity(_view({'R000': {'quantity': 1, 'avg_price': 100}}),
                              _cands(_entries()), {'R000': 100}, sched=sched)
    assert o == []


def test_rebalances_when_interval_reached():
    sched = {'elapsed': m.REBALANCE_DAYS, 'last_seen': '20260825'}
    o = m.decide_us_liquidity(_view({}), _cands(_entries()), {}, sched=sched)
    assert len(_buys(o)) == m.MAX_HOLDINGS


def test_advance_schedule_counts_trading_days_not_calendar():
    sched = {}
    sched = m.advance_schedule(sched, '20260825')
    assert sched['elapsed'] == 0 and sched['last_seen'] == '20260825'
    # 같은 거래일에 여러 번 돌아도 카운터는 안 는다 (장중 루프는 5분마다 돈다)
    sched = m.advance_schedule(sched, '20260825')
    assert sched['elapsed'] == 0
    sched = m.advance_schedule(sched, '20260826')
    assert sched['elapsed'] == 1


def test_mark_rebalanced_resets_counter():
    sched = m.mark_rebalanced({'elapsed': 20, 'last_seen': '20260825'})
    assert sched['elapsed'] == 0


# ── 리밸런스 내용 ────────────────────────────────────────────
def test_buys_exactly_top_n_holdings():
    o = m.decide_us_liquidity(_view({}), _cands(_entries()), {}, sched={})
    codes = [b['code'] for b in _buys(o)]
    assert codes == [f'R{i:03d}' for i in range(m.MAX_HOLDINGS)]


def test_sells_holdings_that_left_the_top_list():
    # R900은 워치리스트에 없다 → 전량 매도
    pf = {'R900': {'quantity': 10, 'avg_price': 50}}
    o = m.decide_us_liquidity(_view(pf), _cands(_entries()), {'R900': 60}, sched={})
    sells = _sells(o)
    assert [s['code'] for s in sells] == ['R900']
    assert sells[0]['quantity'] is None  # 전량


def test_keeps_holdings_still_in_top_list():
    pf = {'R000': {'quantity': 10, 'avg_price': 50}}
    o = m.decide_us_liquidity(_view(pf), _cands(_entries()), {'R000': 60}, sched={})
    assert 'R000' not in [s['code'] for s in _sells(o)]
    assert 'R000' not in [b['code'] for b in _buys(o)]


def test_sizes_by_nav_weight():
    o = m.decide_us_liquidity(_view({}, nav=20000), _cands(_entries(), price=100.0), {}, sched={})
    b = _buys(o)[0]
    assert b['quantity'] == int(20000 * m.POSITION_WEIGHT / 100.0)


def test_skips_zero_price():
    cands = _cands(_entries())
    for c in cands:
        c['price'] = 0
    o = m.decide_us_liquidity(_view({}), cands, {}, sched={})
    assert _buys(o) == []


def test_no_signal_filters_beyond_ranking():
    """기준선 심의 정체성 — 랭킹 외의 '판단'으로 종목을 거르지 않는다.

    가격이 아무리 내려도(과매도) 아무리 올라도(강세) 상위 N이면 산다.
    이 테스트가 깨지면 '잣대'로서의 가치가 사라진다."""
    cands = _cands(_entries())
    cands[0]['price'] = 1.0       # 폭락한 1위
    cands[1]['price'] = 500.0     # 크게 오른 2위 (예산 안에는 든다)
    o = m.decide_us_liquidity(_view({}, nav=20000), cands, {}, sched={})
    bought = {b['code'] for b in _buys(o)}
    assert 'R000' in bought and 'R001' in bought


def test_unaffordable_stock_is_replaced_by_next_rank():
    """포지션 예산으로 1주도 못 사는 종목(BRK.A 류)은 건너뛰고 다음 순위로 채운다.

    이건 판단이 아니라 매수 가능성 제약이다. 그냥 두면 보유 슬롯에 구멍이 나고
    기준선이 '상위 5종목'이 아니라 '상위 5종목 중 살 수 있었던 것'이 된다."""
    cands = _cands(_entries(8), price=100.0)
    cands[1]['price'] = 99999.0   # 2위가 예산 초과
    o = m.decide_us_liquidity(_view({}, nav=20000), cands, {}, sched={})
    codes = [b['code'] for b in _buys(o)]
    assert len(codes) == m.MAX_HOLDINGS
    assert 'R001' not in codes
    assert 'R005' in codes        # 밀린 자리를 다음 순위가 채운다


def test_reason_states_rank():
    o = m.decide_us_liquidity(_view({}), _cands(_entries()), {}, sched={})
    assert '거래대금' in _buys(o)[0]['reason']


# ── 시뮬레이터 클래스 배선 ──────────────────────────────────
def test_simulator_is_paper_and_usd():
    sim = m.USLiquidityBaselineSimulator(initial_cash=20000)
    assert sim.initial_cash == 20000
    assert sim.BUY_FEE_RATE == 0.0  # USBaseSimulator 상속 확인


def test_get_universe_reads_watchlist(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'WATCHLIST_PATH', str(tmp_path / 'wl.json'))
    monkeypatch.setattr(m, 'us_trading_date', lambda: '20260825')
    m.save_watchlist(_entries(3), '20260825')
    sim = m.USLiquidityBaselineSimulator(initial_cash=20000)
    uni = sim.get_universe()
    assert {u['code'] for u in uni} == {'R000', 'R001', 'R002'}
    assert all('avg_dollar_volume' in u for u in uni)
