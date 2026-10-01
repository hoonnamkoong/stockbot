"""Sim14 수축 돌파형(강한횡보 전용, 관찰) — 설계서
docs/superpowers/specs/2026-09-29-new-sideways-sim-design.md §6.1·§7.1·§8.

지키는 것:
  - 진입: 전일 밴드폭(4σ/MA20)이 자기 60일 하위 10% + 장중 현재가 > 직전 20일 고가
          + 5일 평균 거래대금 >= 10억. 필드 부재와 값 미달을 funnel에서 구분한다.
  - 청산: -5% 손절(장중 언제나), MA10 이탈·10거래일 만기(15:15~15:20 마감 직전 루프만).
  - 게이트: 전일 확정 6단계가 강한횡보일 때만 신규 진입. None이면 진입 안 함.
          청산은 국면과 무관하게 항상.
  - 당일 미완성 봉은 지표에 들어가지 않는다(현재가는 돌파 판정에만).
"""
import datetime as dt
import json
import os
import sys
import tempfile

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy import regime_state as rs
from src.strategy.simulators import sim14_squeeze_breakout as m

ROOT = os.path.join(os.path.dirname(__file__), '..')
TODAY = dt.date(2026, 9, 29)


def _kst(hhmm, day=TODAY):
    h, mi = map(int, hhmm.split(':'))
    return dt.datetime(day.year, day.month, day.day, h, mi)


def _weekdays_before(day, n):
    """day 직전까지의 평일 n개(오래된→최신)."""
    out, d = [], day
    while len(out) < n:
        d -= dt.timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out[::-1]


def _series(n=90, squeeze=True, amount=2e9):
    """(dates, closes, highs, amounts). squeeze=True면 마지막 20봉만 잠잠하다."""
    dates = _weekdays_before(TODAY, n)
    closes = []
    for i in range(n):
        calm = (i >= n - 20) if squeeze else (i < n - 20)
        amp = 0.001 if calm else 0.05
        closes.append(10000 * (1 + amp * (-1) ** i))
    highs = [c * 1.01 for c in closes]
    return dates, closes, highs, [amount] * n


def _bars(n=90, squeeze=True, amount=2e9):
    dates, closes, highs, amounts = _series(n, squeeze, amount)
    return {'dates': [d.strftime('%Y-%m-%d') for d in dates],
            'close': closes, 'high': highs, 'amount': amounts}


def _write_csv(path, codes, extra_rows=()):
    lines = ['﻿date,code,name,open,high,low,close,volume,amount']
    for code, (name, kw) in codes.items():
        dates, closes, highs, amounts = _series(**kw)
        for d, c, h, a in zip(dates, closes, highs, amounts):
            lines.append(f"{d.strftime('%Y%m%d')},{code},{name},{c},{h},{c * 0.99},{c},1000,{a}")
    lines += list(extra_rows)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def _view(portfolio=None, nav=3_000_000, cooldown=None):
    return {'portfolio': portfolio or {}, 'cash': nav, 'initial_cash': 3_000_000,
            'nav': nav, 'cooldown_codes': cooldown or {}}


def _cand(code='000001', price=10200.0, squeeze=True, amount=2e9, **over):
    feat, why = m.entry_inputs(_bars(squeeze=squeeze, amount=amount))
    assert why is None, why
    c = {'code': code, 'name': f'종목{code}', 'price': price, **feat,
         **m.exit_inputs(_bars(squeeze=squeeze, amount=amount))}
    c.update(over)
    return c


def _held(code='000001', avg=10000.0, entry_date='2026-09-28', qty=50):
    return {code: {'name': f'종목{code}', 'quantity': qty, 'avg_price': avg,
                   'peak_price': avg, 'entry_date': entry_date, 'is_scaled_out': False}}


# ── 지표(확정 일봉만) ─────────────────────────────────────────────
def test_entry_inputs_squeeze_and_hi20():
    b = _bars(squeeze=True)
    feat, why = m.entry_inputs(b)
    assert why is None
    assert feat['squeeze'] is True
    assert feat['hi20'] == pytest.approx(max(b['high'][-20:]))
    assert feat['amt5'] == pytest.approx(2e9)
    assert feat['bw'] <= feat['bw_q10']


def test_entry_inputs_no_squeeze_when_recent_is_wide():
    feat, why = m.entry_inputs(_bars(squeeze=False))
    assert why is None
    assert feat['squeeze'] is False


def test_entry_inputs_needs_80_bars():
    """60일 분위 + MA20 = 최소 80봉. 모자라면 신호 없음(0으로 채우지 않는다)."""
    feat, why = m.entry_inputs(_bars(n=79))
    assert feat is None and why == 'short_history'
    assert m.entry_inputs(_bars(n=80))[1] is None


def test_entry_inputs_missing_amount_is_unmeasurable_not_zero():
    b = _bars()
    b['amount'][-1] = None
    feat, why = m.entry_inputs(b)
    assert feat is None and why == 'no_amt5'


def test_today_bar_is_excluded_from_indicators():
    """당일 봉(EOD가 쓴 오늘 행)과 미래 날짜 행은 지표에 섞이지 않는다."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'ohlcv_top100.csv')
        today = TODAY.strftime('%Y%m%d')
        _write_csv(p, {'000001': ('가', {})},
                   extra_rows=[f'{today},000001,가,10000,99999,9000,99000,1000,9e12',
                               f'20261001,000001,가,10000,88888,9000,88000,1000,9e12'])
        daily = m.load_daily_bars(p, TODAY)
    bars = daily['000001']
    assert bars['dates'][-1] < TODAY.isoformat()
    assert max(bars['high']) < 99999
    feat, _ = m.entry_inputs(bars)
    assert feat['hi20'] < 11000


def test_unreadable_csv_is_none():
    assert m.load_daily_bars('/no/such/file.csv', TODAY) is None


# ── 진입 결정 ───────────────────────────────────────────────────
def test_buy_on_squeeze_and_breakout():
    funnel = []
    c = _cand(price=10200.0)
    orders = m.decide_sim14(_view(), [c], {}, True, _kst('10:30'), funnel=funnel)
    assert [o['action'] for o in orders] == ['BUY']
    assert orders[0]['quantity'] == int(3_000_000 * 0.19 / 10200.0)
    assert orders[0]['price'] == 10200.0
    # 신호가(hi20)와 가상 체결가를 둘 다 남긴다(설계서 §7.1 슬리피지 실측)
    assert f"{c['hi20']:,.0f}" in orders[0]['reason']


def test_no_buy_without_squeeze():
    funnel = []
    c = _cand(squeeze=False, price=20000.0)
    assert m.decide_sim14(_view(), [c], {}, True, _kst('10:30'), funnel=funnel) == []
    assert funnel[-1]['reason'] == 'no_squeeze'


def test_no_buy_without_breakout():
    funnel = []
    c = _cand(price=10100.0)   # hi20 ≈ 10110
    assert m.decide_sim14(_view(), [c], {}, True, _kst('10:30'), funnel=funnel) == []
    assert funnel[-1]['reason'] == 'no_breakout'


def test_no_buy_when_amt5_below_1bn():
    funnel = []
    c = _cand(amount=9e8)
    assert m.decide_sim14(_view(), [c], {}, True, _kst('10:30'), funnel=funnel) == []
    assert funnel[-1]['reason'] == 'amt5_low'


def test_missing_fields_are_distinguished_from_failed_values():
    """지표 필드 부재(데이터 경로)와 가격 필드 부재(보강 경로)는 다른 사유다."""
    funnel = []
    no_feat = {'code': '000002', 'name': 'x', 'price': 10200.0}
    no_price = _cand(code='000003')
    del no_price['price']
    zero_price = _cand(code='000004', price=0)
    m.decide_sim14(_view(), [no_feat, no_price, zero_price], {}, True, _kst('10:30'),
                   funnel=funnel)
    assert [f['reason'] for f in funnel] == ['no_features', 'no_price_field', 'no_price']


def test_max_five_holdings():
    held = {}
    for i in range(5):
        held.update(_held(code=f'10000{i}'))
    funnel = []
    prices = {c: 10000.0 for c in held}
    orders = m.decide_sim14(_view(portfolio=held), [_cand()], prices, True, _kst('10:30'),
                            funnel=funnel)
    assert orders == []
    assert funnel[-1]['reason'] == 'max_holdings'


def test_cooldown_blocks_same_day_reentry(monkeypatch):
    import src.strategy.simulators.base_simulator as base
    monkeypatch.setattr(base, 'get_kst_date', lambda: TODAY)
    funnel = []
    cd = {'000001': (TODAY + dt.timedelta(days=1)).isoformat()}
    orders = m.decide_sim14(_view(cooldown=cd), [_cand()], {}, True, _kst('10:30'),
                            funnel=funnel)
    assert orders == []
    assert funnel[-1]['reason'] == 'held_or_cooldown'


# ── 게이트 ──────────────────────────────────────────────────────
@pytest.mark.parametrize('r6', list(rs.VALID_REGIMES6) + [None, 'BANANA'])
def test_entry_gate_only_strong_sideways(r6):
    assert m.entry_gate(r6) is (r6 == rs.STRONG_SIDEWAYS)


def test_blocked_regime_no_entry_but_still_exits():
    funnel = []
    held = _held(avg=10000.0)
    orders = m.decide_sim14(_view(portfolio=held), [_cand(code='000009')],
                            {'000001': 9400.0}, False, _kst('10:30'), funnel=funnel)
    assert [(o['action'], o['code']) for o in orders] == [('SELL', '000001')]
    assert any(f['reason'] == 'regime_blocked' for f in funnel)


# ── 청산 ────────────────────────────────────────────────────────
def test_stop_loss_minus5_anytime():
    held = _held(avg=10000.0)
    orders = m.decide_sim14(_view(portfolio=held), [], {'000001': 9500.0}, True, _kst('09:05'))
    assert orders and orders[0]['action'] == 'SELL' and '손절' in orders[0]['reason']
    assert orders[0]['cooldown'] == 1     # 그날 재진입 금지
    assert m.decide_sim14(_view(portfolio=held), [], {'000001': 9510.0}, True,
                          _kst('09:05')) == []


def _exit_cand(closes9, dates):
    return {'code': '000001', 'name': 'x', 'price': 0, 'closes9': closes9, 'bar_dates': dates}


def test_ma10_exit_only_in_closing_window():
    """MA10 = 확정 9봉 + 현재가. 판정은 15:15~15:20 루프에서만."""
    held = _held(avg=10000.0, entry_date='2026-09-25')
    dates = [d.isoformat() for d in _weekdays_before(TODAY, 20)]
    cand = _exit_cand([10500.0] * 9, dates)
    price = {'000001': 10000.0}    # ma10 = 10450 > 10000 → 이탈
    for hhmm in ('10:00', '15:14', '15:20', '15:25'):
        assert m.decide_sim14(_view(portfolio=held), [cand], price, True, _kst(hhmm)) == [], hhmm
    orders = m.decide_sim14(_view(portfolio=held), [cand], price, True, _kst('15:15'))
    assert orders and 'MA10' in orders[0]['reason']


def test_ten_trading_day_expiry():
    dates = [d.isoformat() for d in _weekdays_before(TODAY, 20)]
    cand = _exit_cand([9000.0] * 9, dates)        # 현재가가 MA10 위 → MA10 청산 아님
    price = {'000001': 10000.0}
    held10 = _held(avg=10000.0, entry_date=dates[-10])   # 확정 10거래일 보유
    held9 = _held(avg=10000.0, entry_date=dates[-9])
    orders = m.decide_sim14(_view(portfolio=held10), [cand], price, True, _kst('15:16'))
    assert orders and '10거래일' in orders[0]['reason']
    assert m.decide_sim14(_view(portfolio=held9), [cand], price, True, _kst('15:16')) == []
    assert m.decide_sim14(_view(portfolio=held10), [cand], price, True, _kst('14:00')) == []


def test_exit_inputs_missing_does_not_invent_ma10():
    """확정 봉이 없으면 MA10·보유일을 지어내지 않는다 — 손절만 남는다."""
    held = _held(avg=10000.0, entry_date='2026-09-01')
    notes = []
    orders = m.decide_sim14(_view(portfolio=held), [{'code': '000001', 'price': 9800.0}],
                            {'000001': 9800.0}, True, _kst('15:16'), notes=notes)
    assert orders == []
    assert notes and '000001' in notes[0]


# ── 전일 확정 국면 ───────────────────────────────────────────────
def _write_libero(d, base, regime6_now=None):
    with open(os.path.join(d, rs.regime_state_filename()), 'w', encoding='utf-8') as f:
        json.dump({'regime6': regime6_now,
                   'regime6_state': {'base': base, 'today': None}}, f)


def test_gate_reads_shared_confirmed_helper_not_intraday():
    """Sim14 게이트는 심5·심10과 같은 공용 헬퍼(rs.read_regime6_confirmed)를 쓴다."""
    with tempfile.TemporaryDirectory() as d:
        # 장중 판정이 강한횡보여도 전일 확정(base)이 상승이면 상승이다
        _write_libero(d, {'date': '2026-09-28', 'level': 1, 'vol10': 1.5},
                      regime6_now=rs.STRONG_SIDEWAYS)
        assert rs.read_regime6_confirmed(d) == rs.BULL
        _write_libero(d, {'date': '2026-09-28', 'level': 0, 'vol10': 1.5})
        assert rs.read_regime6_confirmed(d) == rs.STRONG_SIDEWAYS
        _write_libero(d, {'date': '2026-09-28', 'level': 0, 'vol10': 0.5})
        assert rs.read_regime6_confirmed(d) == rs.WEAK_SIDEWAYS
        _write_libero(d, {'date': '2026-09-28', 'level': 0, 'vol10': None})
        assert rs.read_regime6_confirmed(d) is None
        _write_libero(d, None)
        assert rs.read_regime6_confirmed(d) is None
    with tempfile.TemporaryDirectory() as d:
        assert rs.read_regime6_confirmed(d) is None      # 파일 없음


# ── 심 인스턴스(get_universe + run) ─────────────────────────────
def _sim(d, monkeypatch, hhmm='10:30'):
    monkeypatch.setattr(m, 'get_kst_now', lambda: _kst(hhmm))
    monkeypatch.setattr(m, 'log_funnel', lambda *a, **k: None)   # data/에 진단 파일을 안 쓴다
    import src.strategy.simulators.base_simulator as base
    monkeypatch.setattr(base, 'get_kst_date', lambda: TODAY)
    # 생성자의 load_state→reset_state가 실제 data/에 상태 파일을 쓰지 않게 한다.
    monkeypatch.setattr(m.SqueezeBreakoutSimulator, 'load_state', lambda self: None)
    sim = m.SqueezeBreakoutSimulator()
    sim.data_dir = d
    sim.state_file = os.path.join(d, 'sim_squeeze_state.json')
    sim.log_file = os.path.join(d, 'sim_squeeze_log.json')
    sim.csv_file = os.path.join(d, 'trade_history_sim_squeeze.csv')
    sim.reset_state()
    return sim


def _enrich(univ, prices):
    """_enrich_universe 대역 — price만 채운다."""
    return [dict(s, price=prices.get(s['code'], 0)) for s in univ]


def test_universe_and_run_in_strong_sideways(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        _write_csv(os.path.join(d, m.OHLCV_FILENAME), {
            '000001': ('수축', {'squeeze': True}),
            '000002': ('넓음', {'squeeze': False}),
            '000003': ('얇음', {'squeeze': True, 'amount': 5e8}),
            '000004': ('짧음', {'n': 30}),
        })
        _write_libero(d, {'date': '2026-09-28', 'level': 0, 'vol10': 1.5})
        sim = _sim(d, monkeypatch)
        univ = sim.get_universe()
        assert [s['code'] for s in univ] == ['000001']
        assert 'price' not in univ[0]           # 실시간가는 _enrich_universe가 채운다
        assert {f['reason'] for f in sim._pre_funnel} == {'no_squeeze', 'amt5_low', 'short_history'}
        cands = _enrich(univ, {'000001': 10200.0})
        sim.run(cands, current_prices={'000001': 10200.0})
        assert '000001' in sim.state['portfolio']


@pytest.mark.parametrize('level,vol', [(1, 1.5), (0, 0.5), (-1, 1.5), (2, 1.5), (-2, 1.5)])
def test_blocked_regime_universe_is_holdings_only(monkeypatch, level, vol):
    with tempfile.TemporaryDirectory() as d:
        _write_csv(os.path.join(d, m.OHLCV_FILENAME), {'000001': ('수축', {})})
        _write_libero(d, {'date': '2026-09-28', 'level': level, 'vol10': vol})
        sim = _sim(d, monkeypatch)
        assert sim.get_universe() == []
        sim.run(_enrich([{'code': '000001', 'hi20': 1.0, 'squeeze': True, 'amt5': 2e9}],
                        {'000001': 10200.0}), current_prices={'000001': 10200.0})
        assert sim.state['portfolio'] == {}


def test_regime_unknown_no_entry_but_exits_holdings(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        _write_csv(os.path.join(d, m.OHLCV_FILENAME), {'000001': ('수축', {})})
        sim = _sim(d, monkeypatch)             # 리베로 파일 없음 → None
        sim.state['portfolio'] = _held(code='000001', avg=10000.0)
        sim.state['cash'] = 2_500_000
        univ = sim.get_universe()
        assert [s['code'] for s in univ] == ['000001']   # 보유 종목은 청산 재료로 남긴다
        assert 'closes9' in univ[0]
        sim.run(_enrich(univ, {'000001': 9400.0}), current_prices={'000001': 9400.0})
        assert sim.state['portfolio'] == {}


def test_stale_csv_is_not_used(monkeypatch):
    """EOD가 며칠 멈춰 낡은 일봉이면 20일 고가·분위를 옛 값으로 쓰지 않는다."""
    with tempfile.TemporaryDirectory() as d:
        _write_csv(os.path.join(d, m.OHLCV_FILENAME), {'000001': ('수축', {})})
        _write_libero(d, {'date': '2026-09-28', 'level': 0, 'vol10': 1.5})
        sim = _sim(d, monkeypatch)
        monkeypatch.setattr(m, 'get_kst_now', lambda: _kst('10:30', TODAY + dt.timedelta(days=10)))
        assert sim.get_universe() == []
        assert sim._pre_funnel[0]['reason'] == 'stale_daily_csv'


# ── 등록·배선 ───────────────────────────────────────────────────
def test_manifest_registration():
    from src.strategy.registry import get_sim_registry, needs_buzz, get_tradeable_simulator_ids
    reg = {s['id']: s for s in get_sim_registry()}
    s = reg['sim14_squeeze_breakout']
    assert s['state_file'] == 'sim_squeeze_state.json'
    assert s['csv_file'] == 'trade_history_sim_squeeze.csv'
    assert s['tradeable'] is False
    assert needs_buzz('sim14_squeeze_breakout') is False
    assert 'sim14_squeeze_breakout' not in get_tradeable_simulator_ids()
    with open(os.path.join(ROOT, 'src', 'lib', 'sim-registry.generated.ts'), encoding='utf-8') as f:
        ts = f.read()
    assert "id: 'sim14_squeeze_breakout'" in ts
    assert "stateFile: 'sim_squeeze_state.json'" in ts


def test_manifest_block_uses_sim14_module():
    with open(os.path.join(ROOT, 'src', 'strategy', 'strategy_manifest.yaml'), encoding='utf-8') as f:
        sims = {s['id']: s for s in yaml.safe_load(f)['simulators']}
    s = sims['sim14_squeeze_breakout']
    assert s['module'] == 'src.strategy.simulators.sim14_squeeze_breakout'
    assert s['class'] == 'SqueezeBreakoutSimulator'


def test_fields_read_are_supplied_by_universe_or_enrichment(monkeypatch):
    """audit_sim_fields의 정적 절반 — 심이 stock.get()으로 읽는 필드는 전부
    get_universe가 넣거나(지표) _enrich_universe가 넣는다(price)."""
    from scripts.audit_sim_fields import fields_read
    path = os.path.join(ROOT, 'src', 'strategy', 'simulators', 'sim14_squeeze_breakout.py')
    read = set(fields_read(path, 'sim14_squeeze_breakout'))
    assert read, '읽는 필드를 하나도 못 찾았다 — 감사가 이 심을 못 본다'
    with tempfile.TemporaryDirectory() as d:
        _write_csv(os.path.join(d, m.OHLCV_FILENAME), {'000001': ('수축', {})})
        _write_libero(d, {'date': '2026-09-28', 'level': 0, 'vol10': 1.5})
        univ = _sim(d, monkeypatch).get_universe()
    supplied = set(univ[0]) | {'price'}
    assert read <= supplied, f'채워지지 않는 필드: {sorted(read - supplied)}'


def test_state_files_are_deployed_by_manifest():
    """새 상태·매매기록 파일은 하드코딩 없이 매니페스트에서 배포·동기화 목록에 든다
    (trading.yml → trade_loop._write_deploy_manifest, scraper → get_sync_files_list)."""
    from scripts.trade_loop import _write_deploy_manifest, DEPLOY_MANIFEST
    from src.data.storage_manager import StorageManager
    # 인스턴스를 만들면 data/·reports/ 디렉터리를 만든다 — 클래스를 self로 넘긴다
    sync = StorageManager.get_sync_files_list(StorageManager, dt.datetime(2026, 9, 29, 10, 0))
    assert {'sim_squeeze_state.json', 'trade_history_sim_squeeze.csv'} <= set(sync)
    with tempfile.TemporaryDirectory() as d:
        cwd = os.getcwd()
        os.chdir(d)
        try:
            _write_deploy_manifest(None, log=lambda *_: None,
                                   extra_sim_ids={'sim14_squeeze_breakout'})
            with open(DEPLOY_MANIFEST, encoding='utf-8') as f:
                names = f.read().split()
        finally:
            os.chdir(cwd)
    assert {'sim_squeeze_state.json', 'trade_history_sim_squeeze.csv'} <= set(names)
