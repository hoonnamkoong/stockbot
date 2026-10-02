import os, sys
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators import sim11_minervini as sim11
from src.strategy.simulators.sim11_minervini import (
    POSITION_WEIGHT, STOP_PCT, decide_minervini, build_watchlist_entry,
    save_watchlist, load_watchlist, _sma, _trend_template_ok, _vcp_contracting,
)


def _view(portfolio, nav=3_000_000):
    return {'portfolio': portfolio, 'cash': nav, 'initial_cash': 3_000_000, 'nav': nav,
            'cooldown_codes': {}, 'market_index_healthy': True}


MID = datetime(2026, 10, 2, 10, 0)      # 장중(마감 창 밖)
CLOSE = datetime(2026, 10, 2, 15, 16)   # 마감 창 안


def _rising_closes(n=200, start=100.0, step=0.5):
    """단조 증가 종가열. 어떤 구간을 잘라도 최근 평균이 과거 평균보다 높다 —
    MA50>MA150>MA200·MA200 상승추세가 자동으로 성립한다."""
    return [start + i * step for i in range(n)]


def _good_closes():
    """추세 템플릿 + VCP 압축을 둘 다 만족하는 220일 종가열(오늘 미포함).

    0~199일: 완만한 상승(100→199.5) — 정배열·MA200 상승추세 재료.
    200~209일(그 이전 10일): 199.5~201.5 사이 넓게 진동 — 압축 '이전' 구간.
    210~219일(최근 10일): 201.0~201.3 사이 좁게 진동 — VCP 압축 구간.
    """
    base = _rising_closes(200, start=100.0, step=0.5)      # 100.0 ~ 199.5
    prior_tail = [199.5 + (i % 2) * 2.0 for i in range(10)]   # 199.5~201.5, 변동폭 2.0
    recent_tail = [201.0 + (i % 2) * 0.3 for i in range(10)]  # 201.0~201.3, 변동폭 0.3(압축)
    return base + prior_tail + recent_tail


GOOD_CLOSES = _good_closes()          # 오늘 미포함(어제까지)
GOOD_PRICE = 201.2                    # 오늘 종가 — 감시목록 계산엔 이게 마지막 구간에 들어간다
GOOD_W52_LWPR = 90.0                  # price(201.2) >= 90*1.3=117 충족
GOOD_W52_HGPR = 210.0                 # price(201.2) >= 210*0.75=157.5 충족
GOOD_EPS_G = 25.0
GOOD_REV_G = 20.0


def _stock(**kw):
    s = {'code': 'T001', 'name': '추세주', 'price': GOOD_PRICE, 'amount': 50_000_000_000,
         'daily_closes': list(GOOD_CLOSES), 'w52_hgpr': GOOD_W52_HGPR, 'w52_lwpr': GOOD_W52_LWPR,
         'eps_growth_yoy': GOOD_EPS_G, 'revenue_growth_yoy': GOOD_REV_G}
    s.update(kw)
    return s


def _buys(o):
    return [x for x in o if x['action'] == 'BUY']


def _sells(o):
    return [x for x in o if x['action'] == 'SELL']


# ── 순수 헬퍼 ────────────────────────────────────────────
def test_sma_needs_full_window():
    assert _sma([1.0, 2.0, 3.0], 5) is None
    assert _sma([1.0, 2.0, 3.0, 4.0, 5.0], 5) == 3.0


def test_trend_template_passes_on_good_setup():
    assert _trend_template_ok(GOOD_PRICE, GOOD_CLOSES, GOOD_W52_HGPR, GOOD_W52_LWPR) is True


def test_trend_template_fails_below_ma50():
    assert _trend_template_ok(100.0, GOOD_CLOSES, GOOD_W52_HGPR, GOOD_W52_LWPR) is False


def test_trend_template_fails_too_close_to_52w_low():
    """52주 저가 대비 30% 미만 상승이면 아직 바닥권 — 추세 초입이 아니다."""
    assert _trend_template_ok(GOOD_PRICE, GOOD_CLOSES, GOOD_W52_HGPR, w52_lwpr=180.0) is False


def test_trend_template_fails_too_far_below_52w_high():
    assert _trend_template_ok(GOOD_PRICE, GOOD_CLOSES, w52_hgpr=1000.0, w52_lwpr=GOOD_W52_LWPR) is False


def test_trend_template_fails_with_short_history():
    """200+20일 미만이면 MA200 상승추세를 확인할 과거 시점이 없다."""
    assert _trend_template_ok(GOOD_PRICE, GOOD_CLOSES[-210:], GOOD_W52_HGPR, GOOD_W52_LWPR) is False


def test_vcp_contracting_on_good_setup():
    assert _vcp_contracting(GOOD_CLOSES + [GOOD_PRICE]) is True


def test_vcp_no_contraction_when_recent_range_is_not_narrower():
    wide_tail = _rising_closes(200) + [190 + (i % 2) * 20 for i in range(20)]  # 변동폭 20, 안 줄어듦
    assert _vcp_contracting(wide_tail) is False


def _ratio_tail(recent_width: float) -> list[float]:
    """이전 10일 폭 20.0(종가 200 기준) 뒤에 최근 10일 폭 recent_width를 붙인다."""
    prior = [190.0 + (i % 2) * 20.0 for i in range(9)] + [200.0]
    recent = [200.0 - recent_width + (i % 2) * recent_width for i in range(9)] + [200.0]
    return _rising_closes(200) + prior + recent


def test_vcp_ratio_is_085():
    """2026-09-29 0.7→0.85. 폭 비율 0.8은 이제 압축, 0.9는 여전히 아님."""
    assert sim11.CONTRACTION_RATIO == 0.85
    assert _vcp_contracting(_ratio_tail(16.0)) is True    # 0.80 < 0.85 (0.7 기준이면 False)
    assert _vcp_contracting(_ratio_tail(18.0)) is False   # 0.90 >= 0.85


def test_vcp_needs_enough_history():
    assert _vcp_contracting([100.0] * 15) is False


# ── build_watchlist_entry ────────────────────────────────
def test_watchlist_entry_built_on_good_setup():
    e = build_watchlist_entry(_stock())
    assert e is not None
    assert e['name'] == '추세주'
    closes_through_today = GOOD_CLOSES + [GOOD_PRICE]
    assert e['pivot_price'] == max(closes_through_today[-20:])
    assert e['ma50'] == _sma(closes_through_today, 50)


def test_watchlist_entry_none_without_earnings_acceleration():
    assert build_watchlist_entry(_stock(eps_growth_yoy=5.0)) is None


def test_watchlist_entry_none_when_eps_growth_missing():
    """조회 실패로 결손이면 등재 근거가 없다."""
    assert build_watchlist_entry(_stock(eps_growth_yoy=None)) is None


def test_watchlist_entry_none_without_revenue_growth():
    assert build_watchlist_entry(_stock(revenue_growth_yoy=5.0)) is None


def test_watchlist_entry_none_when_trend_template_fails():
    assert build_watchlist_entry(_stock(price=100.0)) is None


def test_watchlist_entry_none_when_not_contracting():
    wide_tail = _rising_closes(200) + [190 + (i % 2) * 20 for i in range(19)]
    assert build_watchlist_entry(_stock(price=210.0, daily_closes=wide_tail)) is None


# ── save_watchlist / load_watchlist ──────────────────────
def test_watchlist_round_trips_for_the_same_date(tmp_path):
    path = str(tmp_path / 'w.json')
    with mock.patch.object(sim11, 'WATCHLIST_PATH', path):
        save_watchlist({'T001': {'name': '추세주', 'pivot_price': 200.0, 'ma50': 150.0}}, '20260820')
        loaded = load_watchlist('20260820')
    assert loaded == {'T001': {'name': '추세주', 'pivot_price': 200.0, 'ma50': 150.0}}


def test_watchlist_rejects_stale_date(tmp_path):
    """날짜가 다르면 빈 감시목록이다 — 낡은 pivot으로 잘못된 시점에 사면 안 된다."""
    path = str(tmp_path / 'w.json')
    with mock.patch.object(sim11, 'WATCHLIST_PATH', path):
        save_watchlist({'T001': {'name': 'x', 'pivot_price': 1.0, 'ma50': 1.0}}, '20260819')
        loaded = load_watchlist('20260820')
    assert loaded == {}


def test_missing_watchlist_file_returns_empty(tmp_path):
    path = str(tmp_path / '없음.json')
    with mock.patch.object(sim11, 'WATCHLIST_PATH', path):
        assert load_watchlist('20260820') == {}


# ── decide_minervini: 진입(실시간가가 pivot을 넘어야 한다) ─
def _watch_stock(**kw):
    s = {'code': 'T001', 'name': '추세주', 'price': 210.0, 'amount': 50_000_000_000,
         'pivot_price': 200.0, 'ma50': 150.0}
    s.update(kw)
    return s


def test_entry_when_price_crosses_pivot_live():
    orders = decide_minervini(_view({}), [_watch_stock()], {'T001': 210.0}, MID)
    b = _buys(orders)
    assert len(b) == 1 and 'pivot' in b[0]['reason']


def test_no_entry_when_price_has_not_reached_pivot():
    orders = decide_minervini(_view({}), [_watch_stock(price=199.0)], {'T001': 199.0}, MID)
    assert _buys(orders) == []


def test_no_entry_exactly_at_pivot():
    """같아도 돌파가 아니다 — 초과해야 한다."""
    orders = decide_minervini(_view({}), [_watch_stock(price=200.0)], {'T001': 200.0}, MID)
    assert _buys(orders) == []


def test_no_entry_when_illiquid():
    orders = decide_minervini(_view({}), [_watch_stock(amount=500_000_000)], {'T001': 210.0}, MID)
    assert _buys(orders) == []


def test_no_entry_without_pivot_price():
    """감시목록에 없는(pivot_price 결손) 종목은 자격이 없다."""
    orders = decide_minervini(_view({}), [_watch_stock(pivot_price=None)], {'T001': 210.0}, MID)
    assert _buys(orders) == []


def test_entry_takes_full_position_weight():
    orders = decide_minervini(_view({}), [_watch_stock()], {'T001': 210.0}, MID)
    b = _buys(orders)[0]
    assert b['quantity'] == int(3_000_000 * POSITION_WEIGHT / 210.0)


def test_max_holdings_caps_entries():
    stocks = [_watch_stock(code=f'T{i:03d}') for i in range(7)]
    prices = {s['code']: 210.0 for s in stocks}
    orders = decide_minervini(_view({}), stocks, prices, MID)
    assert len(_buys(orders)) == 5   # MAX_HOLDINGS


# ── decide_minervini: 청산 ──────────────────────────────
def _held(avg=210.0):
    return {'T001': {'name': '추세주', 'quantity': 10, 'avg_price': avg, 'peak_price': avg}}


def test_hard_stop_fires():
    avg = 1000.0
    stop_price = avg * (1 + STOP_PCT / 100) - 1
    orders = decide_minervini(_view(_held(avg=avg)), [_watch_stock(price=stop_price)],
                              {'T001': stop_price}, MID)
    s = _sells(orders)
    assert len(s) == 1 and '손절' in s[0]['reason']


# 2026-10-02: 50일선 이탈은 장중 즉시 → 마감 창(15:15~15:20) 판정 + EOD 표시
# 익일 첫 사이클 폴백으로 바뀌었다(docs/superpowers/specs/2026-10-02-sim11-ma50-close-exit.md).
# 손절(-7.5%)은 여전히 언제나 본다.
def test_ma50_break_outside_window_does_not_sell():
    """장중(10:00)에 실시간가가 ma50 밑이어도 팔지 않는다 — 마감 창에서만 본다."""
    below_ma = 149.0   # ma50=150
    orders = decide_minervini(_view(_held(avg=155.0)), [_watch_stock(price=below_ma)],
                              {'T001': below_ma}, MID)
    assert _sells(orders) == []


def test_hard_stop_fires_outside_window():
    avg = 1000.0
    stop_price = avg * (1 + STOP_PCT / 100) - 1
    orders = decide_minervini(_view(_held(avg=avg)), [_watch_stock(price=stop_price, ma50=2000.0)],
                              {'T001': stop_price}, datetime(2026, 10, 2, 9, 1))
    s = _sells(orders)
    assert len(s) == 1 and '손절' in s[0]['reason']


def test_exit_below_50day_ma_in_closing_window():
    """MA50(감시목록 값) 아래면 마감 창 사이클에 판다 — 하드손절 폭 안쪽이어도."""
    below_ma = 149.0
    orders = decide_minervini(_view(_held(avg=155.0)), [_watch_stock(price=below_ma)],
                              {'T001': below_ma}, CLOSE)
    s = _sells(orders)
    assert len(s) == 1 and '50일선 이탈(마감 판정)' in s[0]['reason']


def test_closing_window_bounds_match_sim14():
    """15:15 포함, 15:20 미포함(동시호가) — Sim14 EXIT_WINDOW와 같은 비교."""
    from src.strategy.simulators.sim14_squeeze_breakout import EXIT_WINDOW
    assert sim11.MA_EXIT_TIME_WINDOW == EXIT_WINDOW == ('15:15', '15:20')
    below_ma = 149.0

    def sells_at(h, m):
        return _sells(decide_minervini(_view(_held(avg=155.0)), [_watch_stock(price=below_ma)],
                                       {'T001': below_ma}, datetime(2026, 10, 2, h, m)))
    assert sells_at(15, 14) == []
    assert len(sells_at(15, 15)) == 1
    assert len(sells_at(15, 19)) == 1
    assert sells_at(15, 20) == []


def test_ma50_missing_in_window_does_not_sell_and_notes_it():
    """ma50 결손이면 판정 불가 — 지어내서 팔지 않고 사유를 남긴다."""
    notes = []
    orders = decide_minervini(_view(_held(avg=155.0)), [_watch_stock(price=149.0, ma50=None)],
                              {'T001': 149.0}, CLOSE, notes=notes)
    assert _sells(orders) == []
    assert any('T001' in n and 'ma50' in n for n in notes)


def test_exit_next_open_sells_on_first_morning_cycle():
    """EOD가 '전일 종가 < ma50'으로 표시한 보유분은 창 밖(09:01)이어도 첫 사이클에 판다."""
    above_ma = 160.0   # 오늘 실시간가는 ma50 위여도 표시가 우선한다
    orders = decide_minervini(_view(_held(avg=155.0)),
                              [_watch_stock(price=above_ma, exit_next_open=True)],
                              {'T001': above_ma}, datetime(2026, 10, 2, 9, 1))
    s = _sells(orders)
    assert len(s) == 1
    assert '50일선 이탈(전일 종가 판정, 익일 청산)' in s[0]['reason']


def test_exit_next_open_and_window_break_sell_once():
    """표시와 창 판정이 같은 사이클에 겹쳐도 매도는 한 번."""
    below_ma = 149.0
    orders = decide_minervini(_view(_held(avg=155.0)),
                              [_watch_stock(price=below_ma, exit_next_open=True)],
                              {'T001': below_ma}, CLOSE)
    assert len(_sells(orders)) == 1


def test_exit_next_open_without_live_price_does_not_sell():
    """현재가 결손(0)이면 표시가 있어도 팔지 않는다 — 다음 사이클에 다시 본다."""
    orders = decide_minervini(_view(_held(avg=155.0)),
                              [_watch_stock(exit_next_open=True)], {}, datetime(2026, 10, 2, 9, 1))
    assert _sells(orders) == []


def test_no_fixed_take_profit():
    """미너비니 철학 — 승자는 끝까지 탄다. 고정 익절 없음."""
    far_above = 1000.0
    orders = decide_minervini(_view(_held(avg=180.0)), [_watch_stock(price=far_above)],
                              {'T001': far_above}, CLOSE)
    assert _sells(orders) == []


def test_holding_absent_from_candidates_is_not_touched():
    """오늘 후보에 없으면 ma50을 알 수 없다 — 손절폭 밖이면 없는 근거로 팔지 않는다."""
    orders = decide_minervini(
        _view({'ZZZ': {'name': 'x', 'quantity': 10, 'avg_price': 100, 'peak_price': 100}}),
        [], {'ZZZ': 98}, CLOSE)
    assert _sells(orders) == []


# ── get_universe: 오늘자 감시목록만 쓴다 ───────────────────
def test_get_universe_returns_watchlist_without_price():
    """price는 여기서 안 채운다 — _enrich_universe가 실시간 KIS 시세로 채운다."""
    from src.strategy.simulators.sim11_minervini import MinerviniTrendSimulator
    sim = object.__new__(MinerviniTrendSimulator)
    today = sim11.get_kst_now().strftime('%Y%m%d')
    with mock.patch.object(sim11, 'load_watchlist',
                           return_value={'T001': {'name': '추세주', 'pivot_price': 200.0, 'ma50': 150.0}}):
        universe = sim.get_universe()
    # exit_next_open 필드가 없는 옛 감시목록 파일도 그대로 읽힌다(False).
    assert universe == [{'code': 'T001', 'name': '추세주', 'pivot_price': 200.0, 'ma50': 150.0,
                         'exit_next_open': False}]
    assert 'price' not in universe[0]


def test_get_universe_carries_exit_next_open_flag():
    from src.strategy.simulators.sim11_minervini import MinerviniTrendSimulator
    sim = object.__new__(MinerviniTrendSimulator)
    with mock.patch.object(sim11, 'load_watchlist',
                           return_value={'T001': {'name': '보유주', 'pivot_price': None, 'ma50': 150.0,
                                                  'exit_next_open': True}}):
        universe = sim.get_universe()
    assert universe[0]['exit_next_open'] is True
    assert universe[0]['pivot_price'] is None   # 보유 전용 항목 — 재매수 불가 그대로


def test_old_watchlist_file_without_flag_loads(tmp_path):
    """필드 추가 전 포맷 파일(exit_next_open 없음)도 load_watchlist가 그대로 돌려준다."""
    import json as _json
    path = tmp_path / 'w.json'
    path.write_text(_json.dumps({'date': '20261002', 'entries': {
        'T001': {'name': 'x', 'pivot_price': None, 'ma50': 150.0}}}), encoding='utf-8')
    with mock.patch.object(sim11, 'WATCHLIST_PATH', str(path)):
        assert load_watchlist('20261002') == {'T001': {'name': 'x', 'pivot_price': None, 'ma50': 150.0}}


# ── 마감 창 판정 사이클 수(하루 한 줄) ────────────────────
# "창을 놓쳤다"와 "판정했는데 안 걸렸다"는 같은 모양이다(skip-and-nonfire-look-alike).
# 창 안 사이클 수를 state에 날짜별로 세고, 날이 바뀐 첫 사이클에 전일 값을 한 줄 남긴다.
def test_tally_counts_window_cycles_and_reports_on_next_day():
    from src.strategy.simulators.sim11_minervini import tally_ma50_window
    state = {}
    assert tally_ma50_window(state, datetime(2026, 10, 1, 9, 0)) is None
    assert tally_ma50_window(state, datetime(2026, 10, 1, 15, 15)) is None
    assert tally_ma50_window(state, datetime(2026, 10, 1, 15, 17)) is None
    assert tally_ma50_window(state, datetime(2026, 10, 1, 15, 20)) is None   # 창 밖
    assert state['ma50_window'] == {'date': '2026-10-01', 'cycles': 2}
    line = tally_ma50_window(state, datetime(2026, 10, 2, 9, 0))
    assert '2026-10-01' in line and '2회' in line and '놓침' not in line
    assert state['ma50_window'] == {'date': '2026-10-02', 'cycles': 0}


def test_tally_zero_cycles_reports_missed_window():
    from src.strategy.simulators.sim11_minervini import tally_ma50_window
    state = {'ma50_window': {'date': '2026-10-01', 'cycles': 0}}
    line = tally_ma50_window(state, datetime(2026, 10, 2, 9, 0))
    assert '0회' in line and '창 놓침' in line


def test_run_prints_daily_tally_line(capsys):
    from src.strategy.simulators.sim11_minervini import MinerviniTrendSimulator
    sim = object.__new__(MinerviniTrendSimulator)
    sim.state = {'ma50_window': {'date': '2026-10-01', 'cycles': 3}}
    with mock.patch.object(sim11, 'get_kst_now', return_value=datetime(2026, 10, 2, 9, 1)),             mock.patch.object(MinerviniTrendSimulator, 'update_peak_prices'),             mock.patch.object(MinerviniTrendSimulator, '_view', return_value=_view({})),             mock.patch.object(MinerviniTrendSimulator, '_apply'),             mock.patch.object(MinerviniTrendSimulator, 'save_state'),             mock.patch.object(MinerviniTrendSimulator, 'calculate_stats', return_value={}):
        sim.run([], {})
    out = capsys.readouterr().out
    assert '2026-10-01' in out and '3회' in out
    assert sim.state['ma50_window'] == {'date': '2026-10-02', 'cycles': 0}


def test_get_universe_empty_without_todays_watchlist():
    from src.strategy.simulators.sim11_minervini import MinerviniTrendSimulator
    sim = object.__new__(MinerviniTrendSimulator)
    with mock.patch.object(sim11, 'load_watchlist', return_value={}):
        assert sim.get_universe() == []


# ── 감시목록 깔때기 ──────────────────────────────────────
# 2026-09-15: 심11은 후보 100 → 감시목록 1이 평상시 값인데, 그 99가 어디서
# 떨어졌는지 어디에도 기록되지 않았다. build_watchlist_entry가 None만 돌려줘서
# "KIS가 실적을 안 줘서 결손"인지 "실적이 기준 미달"인지 밖에서 구분이 안 됐다.
# 둘은 고치는 곳이 다르다 — 전자는 수집, 후자는 임계값이다.
def _reasons(stock):
    funnel = []
    build_watchlist_entry(stock, funnel=funnel)
    return [f['reason'] for f in funnel]


def test_missing_earnings_is_not_the_same_reason_as_weak_earnings():
    """결손과 미달을 가른다 — 이 구분이 이 깔때기의 존재 이유다."""
    missing = _reasons(_stock(eps_growth_yoy=None))
    weak = _reasons(_stock(eps_growth_yoy=5.0))
    assert missing == ['no_eps']
    assert weak == ['eps_low']


def test_missing_revenue_is_not_the_same_reason_as_weak_revenue():
    assert _reasons(_stock(revenue_growth_yoy=None)) == ['no_revenue']
    assert _reasons(_stock(revenue_growth_yoy=5.0)) == ['revenue_low']


def test_trend_template_records_which_condition_failed():
    """추세 템플릿은 조건이 7개다 — 뭉뚱그리면 어느 손잡이를 돌릴지 모른다.

    GOOD_CLOSES의 MA50은 195.68, MA150은 171.73이다. 195.0은 그 사이라
    정배열(price>MA150>MA200)은 통과하고 `price > MA50`에서만 떨어진다 —
    이 구간이 청산 결함(50일선을 깬 종목은 목록에 못 온다)과 같은 자리다.
    """
    assert _reasons(_stock(price=195.0)) == ['below_ma50']
    assert _reasons(_stock(price=100.0)) == ['not_stacked']
    assert _reasons(_stock(daily_closes=_rising_closes(120))) == ['short_history']


def test_vcp_failure_is_recorded():
    """VCP만 떨어뜨린다 — 표본 길이는 220으로 맞춰 추세 템플릿을 통과시킨다.

    기존 test_watchlist_entry_none_when_not_contracting은 219일짜리를 넘겨
    사실은 short_history로 떨어지고 있었다(깔때기를 붙이고서야 보였다).
    """
    flat_tail = _rising_closes(200) + [199.5 + (i % 2) * 2.0 for i in range(20)]
    assert _reasons(_stock(price=201.2, daily_closes=flat_tail)) == ['no_vcp']


def test_passing_candidate_leaves_no_funnel_row():
    assert _reasons(_stock()) == []
