import os
import tempfile
from unittest import mock

from src.strategy.simulators import us_sim2_donchian as m

# 국내 Sim9-1 테스트(tests/test_sim9_1_donchian.py)와 같은 20일 채널 —
# 이식 정합성을 확인하려고 그대로 재사용한다. build_watchlist_entry로 돌려
# channel_high/channel_low/atr을 얻는다(운영 코드가 실제로 계산하는 값과 동일).
CHANNEL = [900 + (i % 5) * 25 for i in range(19)] + [1000]
_BIG_VOLUME = 1_000_000  # 종가 900~1000 * 이 거래량이면 MIN_AMOUNT를 넉넉히 넘는다


def _entry_fields(closes, avg_dollar_volume=_BIG_VOLUME * 1000.0):
    e = m.build_watchlist_entry('돌파주', closes, avg_dollar_volume)
    assert e is not None
    return {'channel_high': e['channel_high'], 'channel_low': e['channel_low'],
            'atr': e['atr'], 'avg_dollar_volume': e['avg_dollar_volume']}


def _view(portfolio, nav=20000):
    return {'portfolio': portfolio, 'nav': nav, 'cooldown_codes': {}}


def _filler(n=m.MIN_SAMPLE + 2, amount=1_500_000):
    """거래대금 z 표본을 채우는 종목들. 채널 필드가 없어 진입 후보는 아니다.

    avg_dollar_volume을 amount와 같게 둬서 '평소대로 도는' 배경(급증 배수 1.0)을
    만든다 — 급증은 절대 거래대금이 아니라 자기 평균 대비로 재기 때문이다."""
    return [{'code': f'F{i:03d}', 'name': f'중립{i}', 'price': 100,
             'amount': amount, 'avg_dollar_volume': amount}
            for i in range(n)]


def _target(**kw):
    # amount는 avg_dollar_volume(_entry_fields 기본 10억)의 3배 — 돌파에 거래대금이
    # 동반된 상태. 절대값이 아니라 자기 평균 대비 배수로 판정한다.
    s = {'code': 'T001', 'name': '돌파주', 'price': 1050, 'amount': 3_000_000_000}
    s.update(_entry_fields(CHANNEL))
    s.update(kw)
    return s


def _buys(o):
    return [x for x in o if x['action'] == 'BUY']


def _sells(o):
    return [x for x in o if x['action'] == 'SELL']


# ── 워치리스트 진입 조건 ─────────────────────────────────────
def test_build_watchlist_entry_requires_min_channel_days():
    assert m.build_watchlist_entry('짧음', CHANNEL[:12], _BIG_VOLUME * 1000.0) is None


def test_build_watchlist_entry_requires_liquidity():
    assert m.build_watchlist_entry('저유동성', CHANNEL, avg_dollar_volume=1.0) is None


def test_build_watchlist_entry_returns_channel_and_atr():
    e = m.build_watchlist_entry('돌파주', CHANNEL, _BIG_VOLUME * 1000.0)
    assert e['channel_high'] == 1000
    assert e['channel_low'] == min(CHANNEL[-m.EXIT_DAYS:])
    assert e['atr'] > 0


def test_save_and_load_watchlist_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'WATCHLIST_PATH', str(tmp_path / 'sim_us2_donchian_watchlist.json'))
    entries = {'T001': _entry_fields(CHANNEL) | {'name': '돌파주'}}
    m.save_watchlist(entries, '20260823')
    assert m.load_watchlist('20260823') == entries
    assert m.load_watchlist('20260824') == {}  # 날짜 불일치는 빈 딕셔너리(fail-closed)


# ── 진입 판단 ────────────────────────────────────────────
def test_breakout_entry():
    orders = m.decide_us_donchian(_view({}), [_target()] + _filler(), {'T001': 1050})
    b = [o for o in _buys(orders) if o['code'] == 'T001']
    assert len(b) == 1 and '채널 돌파' in b[0]['reason']


def test_no_entry_inside_channel():
    """채널 안이면 돌파가 아니다 — 상단과 같아도 진입하지 않는다."""
    orders = m.decide_us_donchian(_view({}), [_target(price=1000)] + _filler(), {'T001': 1000})
    assert [o for o in _buys(orders) if o['code'] == 'T001'] == []


def test_no_entry_without_volume_confirmation():
    """자기 평균 대비 배수가 배경보다 낮으면(z<=0) 돌파를 믿지 않는다."""
    cands = [_target(amount=1_500_000)] + _filler(amount=50_000_000)
    orders = m.decide_us_donchian(_view({}), cands, {'T001': 1050})
    assert [o for o in _buys(orders) if o['code'] == 'T001'] == []


def test_no_entry_without_channel_high():
    """워치리스트에 channel_high가 없는 후보(EOD가 이력 부족으로 걸렀어야 할
    경우의 방어선)는 진입시키지 않는다."""
    stock = {'code': 'T001', 'name': '돌파주', 'price': 1050, 'amount': 50_000_000,
             'channel_high': None, 'channel_low': None, 'atr': None}
    orders = m.decide_us_donchian(_view({}), [stock] + _filler(), {'T001': 1050})
    assert [o for o in _buys(orders) if o['code'] == 'T001'] == []


def test_no_entry_when_illiquid():
    """유동성 문턱은 실시간 amount가 아니라 워치리스트의 avg_dollar_volume(EOD 평균
    거래대금)으로 판정한다 — 실시간 amount는 거래대금 급증(z-score) 판정에만 쓴다."""
    orders = m.decide_us_donchian(_view({}), [_target(avg_dollar_volume=1.0)] + _filler(),
                                   {'T001': 1050})
    assert [o for o in _buys(orders) if o['code'] == 'T001'] == []


def test_no_signal_when_sample_too_thin():
    orders = m.decide_us_donchian(_view({}), [_target()] + _filler(3), {'T001': 1050})
    assert _buys(orders) == []


def test_entry_takes_full_weight():
    orders = m.decide_us_donchian(_view({}), [_target()] + _filler(), {'T001': 1050})
    b = [o for o in _buys(orders) if o['code'] == 'T001'][0]
    assert b['quantity'] == int(20000 * m.POSITION_WEIGHT / 1050)


# ── 청산 판단 ────────────────────────────────────────────
def _held(avg=1050):
    return {'T001': {'name': '돌파주', 'quantity': 10, 'avg_price': avg, 'peak_price': avg}}


def test_exit_below_10day_channel_low():
    """수익 중이라 10일 저점이 진입가 위로 올라온 상태 — 이때 채널 청산이 이익을 잠근다.
    (진입 직후 손실 구간에서는 2*ATR 손절이 항상 먼저 걸린다.)"""
    rising = [1000 + 10 * i for i in range(20)]      # 10일 저점 1100, ATR 10 → 손절 980
    orders = m.decide_us_donchian(_view(_held(avg=1000)),
                                   [_target(price=1090, **_entry_fields(rising))], {'T001': 1090})
    s = _sells(orders)
    assert len(s) == 1 and '채널 이탈' in s[0]['reason']


def test_atr_stop_fires_before_channel_exit():
    """급락은 채널 저점에 닿기 전에 2*ATR 손절이 먼저 잡는다."""
    orders = m.decide_us_donchian(_view(_held(avg=1050)), [_target(price=920)], {'T001': 920})
    s = _sells(orders)
    assert len(s) == 1 and 'ATR 손절' in s[0]['reason']


def test_no_fixed_take_profit():
    """터틀은 추세를 끝까지 탄다 — 고정 익절 없음."""
    orders = m.decide_us_donchian(_view(_held()), [_target(price=1400)], {'T001': 1400})
    assert _sells(orders) == []


def test_holding_absent_from_candidates_is_not_touched():
    """오늘 후보에 없으면 채널을 계산할 수 없다 — 없는 근거로 팔지 않는다."""
    orders = m.decide_us_donchian(
        _view({'ZZZ': {'name': 'x', 'quantity': 10, 'avg_price': 1000, 'peak_price': 1000}}),
        _filler(), {'ZZZ': 500})
    assert _sells(orders) == []


# ── 심 배선 ────────────────────────────────────────────
def test_us_donchian_simulator_get_universe_reads_todays_watchlist(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'WATCHLIST_PATH', str(tmp_path / 'wl.json'))
    entry = _entry_fields(CHANNEL) | {'name': '돌파주'}
    m.save_watchlist({'T001': entry}, m.us_trading_date())
    with tempfile.TemporaryDirectory() as d:
        sim = m.USDonchianSimulator.__new__(m.USDonchianSimulator)
        sim.name = 'Us2Donchian'
        sim.initial_cash = 20000
        sim.data_dir = d
        sim.state_file = os.path.join(d, 'sim_us2donchian_state.json')
        sim.log_file = os.path.join(d, 'sim_us2donchian_log.json')
        sim.csv_file = os.path.join(d, 'trade_history_sim_us2donchian.csv')
        sim.load_state()
        universe = sim.get_universe()
    assert universe == [{'code': 'T001', 'name': '돌파주',
                          'channel_high': entry['channel_high'],
                          'channel_low': entry['channel_low'], 'atr': entry['atr'],
                          'avg_dollar_volume': entry['avg_dollar_volume']}]


# 2026-08-26 — 유니버스 조회가 복구되자 이 워치리스트가 930종목으로 나왔다.
# MIN_AMOUNT($10M)는 시총 상위 1000 유니버스에서 사실상 아무것도 못 거른다(998→930).
# 장중 루프는 워치리스트 종목마다 개별 호출하므로 930종목이면 한 사이클이
# 약 8분(러너 실측 0.26초/종목) — 잡 타임아웃 4분을 넘긴다.

def _entry(dollar_volume):
    return {'name': 'X', 'channel_high': 10.0, 'channel_low': 8.0,
            'atr': 0.5, 'avg_dollar_volume': dollar_volume}


def test_cap_watchlist_keeps_most_liquid():
    entries = {f'S{i}': _entry(float(i)) for i in range(10)}
    with mock.patch.object(m, 'MAX_WATCHLIST', 3):
        out = m.cap_watchlist(entries)
    assert set(out) == {'S9', 'S8', 'S7'}, '거래대금 상위가 남아야 한다'
    assert out['S9'] == entries['S9'], '엔트리 내용은 그대로여야 한다'


def test_cap_watchlist_leaves_small_watchlist_untouched():
    entries = {f'S{i}': _entry(float(i)) for i in range(3)}
    with mock.patch.object(m, 'MAX_WATCHLIST', 10):
        assert m.cap_watchlist(entries) == entries


def test_cap_watchlist_drops_unmeasured_dollar_volume():
    """거래대금을 모르는 종목을 0으로 취급해 '최하위'로 줄 세우지 않는다 —
    조회 실패가 조용히 후보에서 밀려나기만 하고 사실 자체는 사라진다."""
    entries = {'OK': _entry(5.0), 'UNKNOWN': _entry(None)}
    with mock.patch.object(m, 'MAX_WATCHLIST', 10):
        out = m.cap_watchlist(entries)
    assert set(out) == {'OK'}


# 2026-08-26 실측 — 후보 300종목 중 16종목이 20일 채널 상단을 돌파했는데 매수가
# 0건이었다. `zamt > 0`이 **절대 거래대금의 횡단면 z**라서다: 당일 거래대금 분포는
# 초대형주가 평균을 끌어올려 심하게 치우친다(평균 $469M vs 중앙값 $164M, 최대
# $12,310M). z>0을 통과하는 건 상위 18%뿐이고, 돌파 16종목은 전부 음수였다.
# 게이트 이름은 "거래대금 동반(급증)"인데 실제로 재는 건 "다른 종목보다 큰가"였다.
# 급증은 **그 종목 자신의 평균 대비**로 재야 한다.

def _cand(code, price, ch_hi, amount, avg_dv):
    return {'code': code, 'name': code, 'price': price, 'channel_high': ch_hi,
            'channel_low': ch_hi * 0.9, 'atr': 1.0,
            'amount': amount, 'avg_dollar_volume': avg_dv}


def _empty_view(nav=20000.0):
    return {'portfolio': {}, 'cash': nav, 'nav': nav, 'cooldown_codes': {}}


def _breakout_universe():
    """돌파 1종목(BRK) + 배경 종목들. BRK는 거래대금 절대값은 작지만 자기
    평균 대비로는 크게 늘었다 — 초대형주 배경이 평균을 끌어올린 상황을 재현한다."""
    cands = [_cand('BRK', 110.0, 100.0, 300e6, 100e6)]        # 자기 평균의 3배
    for i in range(15):                                        # 평소대로 도는 초대형주
        cands.append(_cand(f'MEGA{i}', 50.0, 100.0, 5000e6, 5000e6))
    return cands


def test_breakout_with_own_volume_surge_is_bought():
    """절대 거래대금이 작아도 자기 평균 대비 급증했으면 산다."""
    orders = m.decide_us_donchian(_empty_view(), _breakout_universe(),
                                  {c['code']: c['price'] for c in _breakout_universe()})
    buys = [o for o in orders if o['action'] == 'BUY']
    assert [o['code'] for o in buys] == ['BRK'], f'BRK를 사야 한다: {buys}'


def test_breakout_without_volume_surge_is_skipped():
    """자기 평균만큼만 도는 돌파는 '거래대금 동반'이 아니다."""
    cands = _breakout_universe()
    cands[0] = _cand('BRK', 110.0, 100.0, 30e6, 100e6)   # 평균의 0.3배
    orders = m.decide_us_donchian(_empty_view(), cands,
                                  {c['code']: c['price'] for c in cands})
    assert [o for o in orders if o['action'] == 'BUY'] == []


def test_unmeasured_baseline_is_not_treated_as_surge():
    """평균 거래대금을 모르는 종목은 급증 판정에서 뺀다 — 0으로 나누거나
    '측정 불가'를 '급증'으로 바꾸지 않는다."""
    cands = _breakout_universe()
    cands[0] = _cand('BRK', 110.0, 100.0, 300e6, None)
    orders = m.decide_us_donchian(_empty_view(), cands,
                                  {c['code']: c['price'] for c in cands})
    assert [o for o in orders if o['action'] == 'BUY'] == []
