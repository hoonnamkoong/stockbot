"""심15·심16 = 코스피200 대 나스닥100 가속 듀얼모멘텀(ADM), 관찰 심.

정본 사양: docs/superpowers/specs/2026-10-02-max-return-etf.md §9.
- 판정: 069500·133690 각각 (1개월 + 3개월 + 6개월 수익률 합), 직전 완결 월말 종가로만.
- 큰 쪽 점수가 0보다 크면 그 ETF 100%, 아니면 148070 100%.
- 심15는 1배 ETF를, 심16은 판정은 1배로 하고 보유만 2배 ETF(122630·418660)로.
- 월 1회, 보유 종목이 같으면 주문 없음, 판정 불가면 보유 유지 + 같은 달 재시도.
"""
import datetime as dt
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from src.strategy.simulators import sim15_adm as m
from src.strategy.simulators.sim15_adm import (
    JUDGE_ASSETS, SAFE_ASSET, DualMomentumSimulator, adm_score, decide_adm,
    pick_winner, stray_exits,
)
from src.strategy.simulators.sim16_adm_leveraged import LeveragedDualMomentumSimulator

NAV = 3_000_000
KST = dt.timezone(dt.timedelta(hours=9))
KOSPI, NASDAQ = '069500', '133690'
SAFE = '148070'
LEV_KOSPI, LEV_NASDAQ = '122630', '418660'
UNIVERSE_1X = [KOSPI, NASDAQ, SAFE]
FEE = DualMomentumSimulator.BUY_FEE_RATE


def _months_before(month, n):
    y, mo = int(month[:4]), int(month[4:])
    out = []
    for _ in range(n):
        mo -= 1
        if mo == 0:
            y, mo = y - 1, 12
        out.append(f'{y}{mo:02d}')
    return out[::-1]


def _hist(month_end_closes, month='202610', extra_current=True):
    """월말 종가 목록(오래된→최신, 마지막이 month 직전 달) → 일봉 이력.

    월마다 3개 봉이고 월말이 아닌 두 봉은 일부러 다른 값이다 — 월말 봉이 아닌
    값을 쓰면 테스트가 깨진다.
    """
    rows = []
    for ym, close in zip(_months_before(month, len(month_end_closes)), month_end_closes):
        for day, px in ((3, close * 3), (15, close * 0.1), (28, close)):
            rows.append({'date': f'{ym}{day:02d}', 'close': px})
    if extra_current:
        # 진행 중인 달 봉은 판정에 쓰면 룩어헤드다 — 극단값으로 둔다.
        rows.append({'date': f'{month}01', 'close': 1.0})
    return rows


UP = [100] * 6 + [110]       # 점수 +0.30
UP_MORE = [100] * 6 + [120]  # 점수 +0.60
DOWN = [100] * 6 + [90]      # 점수 -0.30


# ── 점수: 1+3+6개월 수익률 합, 완결 월말만 ─────────────────────────

def test_score_is_sum_of_1_3_6_month_returns():
    # 월말: 6개월 전 100, 3개월 전 110, 1개월 전 120, 직전 132
    score, info = adm_score(_hist([100, 999, 999, 110, 999, 120, 132]), '202610')
    assert score == pytest.approx(0.10 + 0.20 + 0.32)
    assert info['close'] == 132


def test_score_ignores_current_month_bars():
    """이번 달 봉(1원)이 섞여도 직전 완결 월말만 본다."""
    score, _ = adm_score(_hist(UP), '202610')
    assert score == pytest.approx(0.30)


def test_score_uses_only_last_seven_month_ends():
    """7개월 전 월말(아주 큼)은 계산에 안 들어간다."""
    score, _ = adm_score(_hist([10_000] + UP), '202610')
    assert score == pytest.approx(0.30)


@pytest.mark.parametrize('hist,reason', [
    ([], 'no_history'),
    (_hist([100] * 6), 'short_history'),        # 완결 월 6개 — 6개월 수익에 7개가 필요
    (_hist(UP, month='202609', extra_current=False), 'stale_history'),
    ([r for r in _hist([100] + UP) if not r['date'].startswith('202606')], 'gap_history'),
    (_hist([0] + [100] * 6), 'bad_close'),
])
def test_score_undeterminable(hist, reason):
    score, info = adm_score(hist, '202610')
    assert score is None and info['reason'] == reason


# ── 승자 선택 ──────────────────────────────────────────────────────

def test_winner_is_higher_score():
    assert pick_winner({KOSPI: 0.1, NASDAQ: 0.4}) == NASDAQ
    assert pick_winner({KOSPI: 0.5, NASDAQ: 0.4}) == KOSPI


def test_winner_tie_goes_to_first_judge_asset():
    """문서에 동점 규칙이 없다 — 판정 자산 나열 순서(069500 먼저)로 결정적으로 정한다."""
    assert pick_winner({NASDAQ: 0.2, KOSPI: 0.2}) == KOSPI


@pytest.mark.parametrize('scores', [
    {KOSPI: -0.1, NASDAQ: -0.3},
    {KOSPI: 0.0, NASDAQ: -0.3},      # 0은 '0보다 크다'가 아니다
])
def test_non_positive_winner_means_safe_asset(scores):
    assert pick_winner(scores) is None


# ── 주문 산출(순수 함수) ───────────────────────────────────────────

def _view(portfolio=None, cash=NAV, nav=NAV):
    return {'portfolio': portfolio or {}, 'cash': cash, 'nav': nav,
            'initial_cash': NAV, 'cooldown_codes': {}}


def _held(qty, avg=10_000):
    return {'name': 'x', 'quantity': qty, 'avg_price': avg}


def _prices(px=10_000, codes=UNIVERSE_1X):
    return {c: px for c in codes}


def _universe():
    return JUDGE_ASSETS + [SAFE_ASSET]


def test_empty_portfolio_buys_target_with_all_cash_integer_shares():
    px = 109_545
    orders = decide_adm(_view(), _prices(px), KOSPI, _universe())
    assert [(o['action'], o['code']) for o in orders] == [('BUY', KOSPI)]
    qty = orders[0]['quantity']
    assert isinstance(qty, int) and qty == int(NAV / (px * (1 + FEE))) == 27
    left = NAV - qty * px * (1 + FEE)
    assert 0 <= left < px * (1 + FEE)             # 잔여 현금은 1주 값 미만


def test_same_holding_means_no_order():
    funnel = []
    orders = decide_adm(_view({KOSPI: _held(290)}, cash=100_000), _prices(), KOSPI,
                        _universe(), funnel)
    assert orders == []
    assert {'code': KOSPI, 'reason': 'hold_same'} in funnel


def test_switch_sells_everything_first_then_buys():
    """현금 0에서 매도 대금으로 산다 — 매도가 먼저여야 현금 부족이 안 난다."""
    orders = decide_adm(_view({KOSPI: _held(300)}, cash=0), _prices(), NASDAQ, _universe())
    assert [(o['action'], o['code']) for o in orders] == [('SELL', KOSPI), ('BUY', NASDAQ)]
    assert orders[0]['quantity'] is None                    # 전량
    proceeds = 300 * 10_000 * (1 - DualMomentumSimulator.SELL_FEE_RATE)   # ETF 면세
    assert orders[1]['quantity'] == int(proceeds / (10_000 * (1 + FEE)))


def test_switch_to_safe_asset():
    orders = decide_adm(_view({NASDAQ: _held(300)}, cash=0), _prices(), SAFE, _universe())
    assert [(o['action'], o['code']) for o in orders] == [('SELL', NASDAQ), ('BUY', SAFE)]


@pytest.mark.parametrize('missing', [KOSPI, NASDAQ])
def test_missing_price_on_either_leg_means_no_order_at_all(missing):
    """팔 종목이나 살 종목 가격이 없으면 한쪽만 체결하지 않는다(전량 교체는 한 묶음)."""
    px = _prices()
    px[missing] = 0
    funnel = []
    orders = decide_adm(_view({KOSPI: _held(300)}, cash=0), px, NASDAQ, _universe(), funnel)
    assert orders == []
    assert {'code': missing, 'reason': 'no_price'} in funnel


def test_too_little_cash_for_one_share_is_recorded():
    funnel = []
    orders = decide_adm(_view(cash=5_000, nav=5_000), _prices(), KOSPI, _universe(), funnel)
    assert orders == []
    assert any(f['code'] == KOSPI and f['reason'] == 'qty_zero' for f in funnel)


def test_stray_exits_sell_holdings_outside_universe():
    pf = {'005930': _held(3), KOSPI: _held(1)}
    orders = stray_exits(_view(pf), {'005930': 70_000, KOSPI: 10_000}, set(UNIVERSE_1X))
    assert [(o['action'], o['code'], o['quantity']) for o in orders] == [('SELL', '005930', None)]


def test_stray_without_price_is_not_sold():
    funnel = []
    assert stray_exits(_view({'005930': _held(3)}), {}, set(UNIVERSE_1X), funnel) == []
    assert funnel == [{'code': '005930', 'reason': 'stray_no_price'}]


# ── run(): 월 1회 게이트·판정 불가·재시도 ──────────────────────────

def _sim(tmp_path, monkeypatch, now, history, cls=DualMomentumSimulator, trading_day=True):
    """실제 data/를 건드리지 않게 생성자를 거치지 않고 만든다(상태 파일이 없으면
    생성자가 data/에 새 파일을 쓴다)."""
    monkeypatch.setattr(m, 'log_funnel', lambda *a, **k: None)
    s = cls.__new__(cls)
    s.name = 'T'
    s.initial_cash = NAV
    s.data_dir = str(tmp_path)
    s.state_file = str(tmp_path / 'state.json')
    s.log_file = str(tmp_path / 'log.json')
    s.csv_file = str(tmp_path / 'hist.csv')
    s.reset_state()
    monkeypatch.setattr(m, 'get_kst_now', lambda: now)
    monkeypatch.setattr(m.AdmBase, '_is_trading_day', staticmethod(lambda ymd: trading_day))
    calls = []

    def fetch(self, code):
        calls.append(code)
        return list(history(code))
    monkeypatch.setattr(m.AdmBase, '_fetch_history', fetch)
    return s, calls


def _by_code(**kw):
    table = {KOSPI: kw['kospi'], NASDAQ: kw['nasdaq']}
    return lambda code: table[code]


OCT1 = dt.datetime(2026, 10, 1, 9, 30, tzinfo=KST)
NOV2 = dt.datetime(2026, 11, 2, 9, 30, tzinfo=KST)
ALL = [KOSPI, NASDAQ, SAFE, LEV_KOSPI, LEV_NASDAQ]


def _qty(s):
    return {c: p['quantity'] for c, p in s.state['portfolio'].items()}


def test_first_run_of_month_buys_winner_once(tmp_path, monkeypatch):
    s, calls = _sim(tmp_path, monkeypatch, OCT1,
                    _by_code(kospi=_hist(UP_MORE), nasdaq=_hist(UP)))
    s.run([], _prices(codes=ALL))
    assert set(s.state['portfolio']) == {KOSPI}
    assert s.state['portfolio'][KOSPI]['quantity'] == int(NAV / (10_000 * (1 + FEE)))
    assert 0 <= s.state['cash'] < 10_000 * (1 + FEE)
    assert s.state['adm_rebalanced_month'] == '202610'
    assert calls == [KOSPI, NASDAQ]

    before = _qty(s)
    calls.clear()
    s.run([], _prices(20_000, ALL))                   # 같은 달 두 번째 런
    assert calls == []                                # 이력 조회조차 안 한다
    assert _qty(s) == before


def test_both_scores_non_positive_buys_safe_asset(tmp_path, monkeypatch):
    s, _ = _sim(tmp_path, monkeypatch, OCT1, _by_code(kospi=_hist(DOWN), nasdaq=_hist(DOWN)))
    s.run([], _prices(codes=ALL))
    assert set(s.state['portfolio']) == {SAFE}


def test_next_month_same_winner_makes_no_trade(tmp_path, monkeypatch):
    s, calls = _sim(tmp_path, monkeypatch, OCT1,
                    _by_code(kospi=_hist(UP_MORE), nasdaq=_hist(UP)))
    s.run([], _prices(codes=ALL))
    before, cash = _qty(s), s.state['cash']

    monkeypatch.setattr(m, 'get_kst_now', lambda: NOV2)
    nov = _by_code(kospi=_hist(UP_MORE, month='202611'), nasdaq=_hist(UP, month='202611'))
    monkeypatch.setattr(m.AdmBase, '_fetch_history',
                        lambda self, code: (calls.append(code), list(nov(code)))[1])
    calls.clear()
    s.run([], _prices(12_000, ALL))
    assert calls == [KOSPI, NASDAQ]                   # 새 달은 다시 판정한다
    assert _qty(s) == before and s.state['cash'] == cash
    assert s.state['adm_rebalanced_month'] == '202611'


def test_next_month_new_winner_replaces_whole_position(tmp_path, monkeypatch):
    s, calls = _sim(tmp_path, monkeypatch, OCT1,
                    _by_code(kospi=_hist(UP_MORE), nasdaq=_hist(UP)))
    s.run([], _prices(codes=ALL))

    monkeypatch.setattr(m, 'get_kst_now', lambda: NOV2)
    nov = _by_code(kospi=_hist(UP, month='202611'), nasdaq=_hist(UP_MORE, month='202611'))
    monkeypatch.setattr(m.AdmBase, '_fetch_history', lambda self, code: list(nov(code)))
    s.run([], _prices(codes=ALL))
    assert set(s.state['portfolio']) == {NASDAQ}
    assert s.state['cash'] < 10_000 * (1 + FEE)       # 매도 대금 전액을 다시 넣었다


@pytest.mark.parametrize('now,trading', [
    (dt.datetime(2026, 10, 1, 8, 30, tzinfo=KST), True),    # 개장 전
    (dt.datetime(2026, 10, 1, 15, 40, tzinfo=KST), True),   # 마감 후
    (OCT1, False),                                          # 휴장일
])
def test_no_rebalance_outside_session(tmp_path, monkeypatch, now, trading):
    s, calls = _sim(tmp_path, monkeypatch, now,
                    _by_code(kospi=_hist(UP), nasdaq=_hist(UP)), trading_day=trading)
    s.run([], _prices(codes=ALL))
    assert s.state['portfolio'] == {} and calls == []
    assert 'adm_rebalanced_month' not in s.state


@pytest.mark.parametrize('broken', [KOSPI, NASDAQ])
def test_one_undeterminable_asset_holds_position_and_retries(tmp_path, monkeypatch, broken):
    """둘 중 하나라도 판정 불가면 부분 판정으로 갈아타지 않는다 — 보유 유지, 같은 달 재시도."""
    fail = {'on': True}
    good = {KOSPI: _hist(DOWN), NASDAQ: _hist(UP)}     # 판정되면 나스닥이 이긴다
    s, calls = _sim(tmp_path, monkeypatch, OCT1,
                    lambda code: [] if (code == broken and fail['on']) else good[code])
    s.state['portfolio'] = {KOSPI: dict(_held(290), peak_price=10_000)}
    s.state['cash'], s.state['invested'] = 100_000, 2_900_000

    s.run([], _prices(codes=ALL))
    assert _qty(s) == {KOSPI: 290} and s.state['cash'] == 100_000
    assert 'adm_rebalanced_month' not in s.state      # 이번 달을 소모하지 않는다

    fail['on'] = False
    calls.clear()
    s.run([], _prices(codes=ALL))                      # 다음 사이클이 다시 시도
    assert calls == [KOSPI, NASDAQ]
    assert set(s.state['portfolio']) == {NASDAQ}
    assert s.state['adm_rebalanced_month'] == '202610'


def test_missing_live_price_defers_without_consuming_month(tmp_path, monkeypatch):
    s, _ = _sim(tmp_path, monkeypatch, OCT1, _by_code(kospi=_hist(UP_MORE), nasdaq=_hist(UP)))
    px = _prices(codes=ALL)
    px[KOSPI] = 0
    s.run([], px)
    assert s.state['portfolio'] == {} and 'adm_rebalanced_month' not in s.state
    s.run([], _prices(codes=ALL))
    assert set(s.state['portfolio']) == {KOSPI}


def test_stray_holding_is_liquidated_regardless_of_gate(tmp_path, monkeypatch):
    s, calls = _sim(tmp_path, monkeypatch, dt.datetime(2026, 10, 1, 8, 0, tzinfo=KST),
                    _by_code(kospi=_hist(UP), nasdaq=_hist(UP)))
    s.state['portfolio'] = {'005930': dict(_held(3, 70_000), peak_price=70_000)}
    s.state['cash'], s.state['invested'] = NAV - 210_000, 210_000
    s.run([], {'005930': 70_000})
    assert s.state['portfolio'] == {} and calls == []


def test_last_decision_is_recorded_for_audit(tmp_path, monkeypatch):
    s, _ = _sim(tmp_path, monkeypatch, OCT1, _by_code(kospi=_hist(UP), nasdaq=_hist(UP_MORE)))
    s.run([], _prices(codes=ALL))
    last = s.state['adm_last_decision']
    assert last['winner'] == NASDAQ and last['target'] == NASDAQ
    assert last['scores'][KOSPI]['score'] == pytest.approx(0.30)
    assert last['scores'][NASDAQ]['score'] == pytest.approx(0.60)


def test_universe_is_literal_etfs_without_price():
    """price를 안 줘야 _enrich_universe가 KIS 실시간가로 채운다."""
    u = DualMomentumSimulator.__new__(DualMomentumSimulator).get_universe()
    assert [e['code'] for e in u] == UNIVERSE_1X
    assert all('price' not in e for e in u)


# ── 심16: 판정은 1배, 보유는 2배 ───────────────────────────────────

@pytest.mark.parametrize('kospi,nasdaq,held', [
    (UP_MORE, UP, LEV_KOSPI),
    (UP, UP_MORE, LEV_NASDAQ),
    (DOWN, DOWN, SAFE),
])
def test_sim16_judges_on_1x_and_holds_2x(tmp_path, monkeypatch, kospi, nasdaq, held):
    s, calls = _sim(tmp_path, monkeypatch, OCT1,
                    _by_code(kospi=_hist(kospi), nasdaq=_hist(nasdaq)),
                    cls=LeveragedDualMomentumSimulator)
    s.run([], _prices(codes=ALL))
    assert calls == [KOSPI, NASDAQ]                   # 점수는 1배 ETF 가격으로
    assert set(s.state['portfolio']) == {held}


def test_sim16_universe_is_the_held_etfs():
    u = LeveragedDualMomentumSimulator.__new__(LeveragedDualMomentumSimulator).get_universe()
    assert [e['code'] for e in u] == [LEV_KOSPI, LEV_NASDAQ, SAFE]
    assert all('price' not in e for e in u)


def test_sim16_treats_1x_holding_as_stray(tmp_path, monkeypatch):
    """심16 장부에 1배 ETF가 있으면 유니버스 밖이다 — 청산한다."""
    s, _ = _sim(tmp_path, monkeypatch, dt.datetime(2026, 10, 1, 8, 0, tzinfo=KST),
                _by_code(kospi=_hist(UP), nasdaq=_hist(UP)),
                cls=LeveragedDualMomentumSimulator)
    s.state['portfolio'] = {KOSPI: dict(_held(10), peak_price=10_000)}
    s.state['cash'], s.state['invested'] = NAV - 100_000, 100_000
    s.run([], _prices(codes=ALL))
    assert s.state['portfolio'] == {}


# ── 등록: 매니페스트·화이트리스트·배포 목록 ────────────────────────

SIM_IDS = {'sim15_adm': ('sim_adm_state.json', 'trade_history_sim_adm.csv'),
           'sim16_adm_lev': ('sim_admlev_state.json', 'trade_history_sim_admlev.csv')}


def test_both_sims_are_registered_as_observation_only():
    from src.strategy.registry import (
        get_sim_registry, get_tradeable_simulator_ids, list_buzz_free_sim_ids, needs_buzz)
    reg = {s['id']: s for s in get_sim_registry()}
    for sim_id, (state_file, csv_file) in SIM_IDS.items():
        assert reg[sim_id]['tradeable'] is False
        assert (reg[sim_id]['state_file'], reg[sim_id]['csv_file']) == (state_file, csv_file)
        assert sim_id not in get_tradeable_simulator_ids()
        assert needs_buzz(sim_id) is False
        assert sim_id in list_buzz_free_sim_ids(None)   # 60초 루프에서 돈다


def test_leveraged_sim_description_states_account_requirements():
    import yaml
    path = os.path.join(os.path.dirname(__file__), '..', 'src', 'strategy',
                        'strategy_manifest.yaml')
    with open(path, encoding='utf-8') as f:
        sims = {s['id']: s for s in yaml.safe_load(f)['simulators']}
    desc = sims['sim16_adm_lev']['description']
    assert '레버리지 ETF' in desc and '사전교육' in desc and '예탁금' in desc


def test_state_files_are_deployed_by_manifest():
    """새 상태·매매기록 파일은 하드코딩 없이 매니페스트에서 배포·동기화 목록에 든다
    (trading.yml → trade_loop._write_deploy_manifest, scraper → get_sync_files_list)."""
    from scripts.trade_loop import _write_deploy_manifest, DEPLOY_MANIFEST
    from src.data.storage_manager import StorageManager
    expected = {name for pair in SIM_IDS.values() for name in pair}
    # 인스턴스를 만들면 data/·reports/ 디렉터리를 만든다 — 클래스를 self로 넘긴다
    sync = StorageManager.get_sync_files_list(StorageManager, dt.datetime(2026, 10, 5, 10, 0))
    assert expected <= set(sync)
    with tempfile.TemporaryDirectory() as d:
        cwd = os.getcwd()
        os.chdir(d)
        try:
            _write_deploy_manifest(None, log=lambda *_: None, extra_sim_ids=set(SIM_IDS))
            with open(DEPLOY_MANIFEST, encoding='utf-8') as f:
                names = f.read().split()
        finally:
            os.chdir(cwd)
    assert expected <= set(names)
