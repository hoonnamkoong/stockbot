from unittest import mock

from scripts.run_eod_sim_us import build_watchlists_for_universe, main as eod_main
from src.strategy.simulators.us_sim2_donchian import MIN_AMOUNT as SIM2_MIN_AMOUNT


def _uptrend_closes(n=230, start=50.0, step=0.15):
    return [round(start + i * step, 2) for i in range(n)]


def _uptrend_with_vcp_closes():
    """200일 이상 상승 추세 뒤, 최근 10일 변동폭이 그 이전 10일보다 좁아지는
    VCP(변동성 수축) 패턴을 덧붙인다. 순수 선형 상승만으로는 _vcp_contracting이
    False라(수축 없이 등폭이라) build_watchlist_entry를 통과하지 못한다."""
    base = _uptrend_closes(210)
    last = base[-1]
    prior = [round(last + d, 2) for d in (2, 4, 0, 3, 1, 4.5, 0.5, 3.5, 1.5, 4)]
    recent = [round(last + 5 + d, 2) for d in (0, 0.3, -0.2, 0.2, -0.1, 0.3, -0.1, 0.1, 0.0, 0.2)]
    return base + prior + recent


def _bars(closes, volume=0):
    """close 이력을 EOD 배치가 기대하는 bar 딕셔너리 목록으로 변환."""
    return [{'close': c, 'high': c, 'low': c, 'volume': volume} for c in closes]


# 220일치 상승 이력 + 하루치 큰 거래량 → Sim1(미너비니) 탈락(VCP 수축 없음),
# Sim2(돈치안) 통과에 필요한 최소 거래대금은 충분(220일 내내 volume을 주므로
# 최근 20일 평균거래대금 = close*volume 그대로).
_SIM2_ONLY_VOLUME = int(SIM2_MIN_AMOUNT / 50.0) + 1_000  # 종가 근사 50 기준 여유있게 통과


@mock.patch('scripts.run_eod_sim_us.time.sleep')
def test_build_watchlist_skips_short_history_without_fundamentals_call(mock_sleep):
    universe = [{'symbol': 'NEWCO', 'name': 'New Co', 'market_cap': 1e9}]
    fetch_ohlcv = mock.Mock(return_value=_bars([10.0] * 30, volume=1_000_000))
    fetch_fund = mock.Mock()
    out1, out2, out3 = build_watchlists_for_universe(
        universe, cik_map={'NEWCO': '0000000001'},
        fetch_ohlcv=fetch_ohlcv, fetch_fundamentals=fetch_fund)
    assert out1 == {}
    assert out2 == {}
    fetch_fund.assert_not_called()  # 추세 템플릿 탈락 종목엔 EDGAR 콜을 안 낸다


@mock.patch('scripts.run_eod_sim_us.time.sleep')
def test_build_watchlist_includes_symbol_passing_all_filters(mock_sleep):
    closes = _uptrend_with_vcp_closes()
    bars = _bars(closes, volume=_SIM2_ONLY_VOLUME)
    universe = [{'symbol': 'AAPL', 'name': 'Apple Inc.', 'market_cap': 3e12}]
    fetch_ohlcv = mock.Mock(return_value=bars)
    fetch_fund = mock.Mock(return_value={'eps_growth_yoy': 25.0, 'revenue_growth_yoy': 20.0})
    out1, out2, out3 = build_watchlists_for_universe(
        universe, cik_map={'AAPL': '0000320193'},
        fetch_ohlcv=fetch_ohlcv, fetch_fundamentals=fetch_fund)
    assert 'AAPL' in out1
    fetch_fund.assert_called_once_with('0000320193')
    # 야후 스로틀(종목마다) + SEC EDGAR 스로틀(템플릿 통과 종목만) = 2회
    assert mock_sleep.call_count == 2
    # 추세 템플릿을 통과한 종목은 거래대금 조건도 넉넉히 충족하므로 Sim2도 같이 통과.
    assert 'AAPL' in out2


@mock.patch('scripts.run_eod_sim_us.time.sleep')
def test_build_watchlist_skips_symbol_without_cik(mock_sleep):
    closes = _uptrend_closes()
    bars = _bars(closes, volume=_SIM2_ONLY_VOLUME)
    universe = [{'symbol': 'NOCIK', 'name': 'No Cik', 'market_cap': 1e9}]
    fetch_ohlcv = mock.Mock(return_value=bars)
    fetch_fund = mock.Mock()
    out1, out2, out3 = build_watchlists_for_universe(
        universe, cik_map={}, fetch_ohlcv=fetch_ohlcv, fetch_fundamentals=fetch_fund)
    assert out1 == {}
    fetch_fund.assert_not_called()
    # CIK가 없어 Sim1은 탈락해도, Sim2는 펀더멘털이 필요 없으므로 독립적으로 평가된다
    # (단, 이 종가는 VCP 수축이 없어 Sim1 추세템플릿 통과 여부와 무관하게 채널 계산만
    # 확인하면 된다 — 이력 20일 이상 + 거래대금 충분이면 통과).
    assert 'NOCIK' in out2


@mock.patch('scripts.run_eod_sim_us.time.sleep')
def test_build_watchlist_survives_single_symbol_fetch_failure(mock_sleep):
    """상장폐지·티커 불일치 한 건이 배치 전체를 죽이면 그날 워치리스트가 통째로 빈다."""
    closes = _uptrend_with_vcp_closes()
    bars = _bars(closes, volume=_SIM2_ONLY_VOLUME)

    def fetch_ohlcv(symbol):
        if symbol == 'DEAD':
            raise RuntimeError('404 Not Found')
        return bars

    universe = [{'symbol': 'DEAD', 'name': 'Delisted Co', 'market_cap': 1e8},
                {'symbol': 'AAPL', 'name': 'Apple Inc.', 'market_cap': 3e12}]
    fetch_fund = mock.Mock(return_value={'eps_growth_yoy': 25.0, 'revenue_growth_yoy': 20.0})
    out1, out2, out3 = build_watchlists_for_universe(
        universe, cik_map={'AAPL': '0000320193'},
        fetch_ohlcv=fetch_ohlcv, fetch_fundamentals=fetch_fund)
    assert 'AAPL' in out1
    assert 'DEAD' not in out1
    assert 'AAPL' in out2
    assert 'DEAD' not in out2


@mock.patch('scripts.run_eod_sim_us.time.sleep')
def test_sim2_excluded_when_dollar_volume_too_low(mock_sleep):
    """220일 이력은 충분해도 거래대금이 문턱 미달이면 Sim2 워치리스트에서 빠진다."""
    closes = _uptrend_closes()  # VCP 수축 없어 Sim1도 어차피 탈락
    bars = _bars(closes, volume=1)  # 종가×1 ≈ 문턱에 한참 못 미침
    universe = [{'symbol': 'THIN', 'name': 'Thin Co', 'market_cap': 1e9}]
    fetch_ohlcv = mock.Mock(return_value=bars)
    fetch_fund = mock.Mock()
    out1, out2, out3 = build_watchlists_for_universe(
        universe, cik_map={}, fetch_ohlcv=fetch_ohlcv, fetch_fundamentals=fetch_fund)
    assert out1 == {}
    assert out2 == {}


# 2026-08-26 — 이 배치는 08-24·08-25 두 번 다 유니버스 조회에서 예외로 죽었는데,
# 빨간 X가 Actions 로그에만 남아 이틀 동안 아무도 몰랐다. 그 사이 장중 루프는
# 빈 워치리스트로 계속 돌아 매매가 0건이었다. 실패는 사람에게 가야 한다.

def _patch_main(**kw):
    """main()의 네트워크·저장을 전부 막고 알림만 관찰한다."""
    defaults = {
        'fetch_us_universe': mock.DEFAULT, 'filter_universe': mock.DEFAULT,
        'save_universe': mock.DEFAULT, 'fetch_cik_map': mock.DEFAULT,
        'build_watchlists_for_universe': mock.DEFAULT,
        'save_sim1_watchlist': mock.DEFAULT, 'save_sim2_watchlist': mock.DEFAULT,
        'save_sim3_watchlist': mock.DEFAULT,
        # US Sim4 점수 산출은 SEC·FINRA를 친다 — 여기서는 막고, 아래 전용 테스트가 본다.
        'refresh_sim4_watchlist': mock.DEFAULT,
    }
    defaults.update(kw)
    return mock.patch.multiple('scripts.run_eod_sim_us', **defaults)


def test_main_alerts_and_reraises_on_failure():
    """실패는 알리되 예외를 삼키지 않는다 — 잡이 초록으로 끝나면 안 된다."""
    with _patch_main(fetch_us_universe=mock.Mock(side_effect=RuntimeError('스크리너 빈 응답'))), \
         mock.patch('scripts.run_eod_sim_us.alerts.send_alert') as alert:
        try:
            eod_main()
            assert False, '예외가 그대로 올라와야 한다'
        except RuntimeError:
            pass
    assert alert.called, '실패가 조용히 묻혔다'
    assert '스크리너 빈 응답' in alert.call_args.args[0], '원인이 알림에 없다'


def test_main_alerts_when_all_watchlists_empty():
    """예외 없이 끝나도 세 워치리스트가 전부 비면 다음 날 매매가 0건이 된다."""
    with _patch_main(filter_universe=mock.Mock(return_value=[{'symbol': 'AAPL'}]),
                     build_watchlists_for_universe=mock.Mock(return_value=({}, {}, {}))), \
         mock.patch('scripts.run_eod_sim_us.alerts.send_alert') as alert:
        eod_main()
    assert alert.called, '전부 빈 워치리스트를 성공으로 넘겼다'


def test_main_does_not_alert_when_any_watchlist_filled():
    with _patch_main(filter_universe=mock.Mock(return_value=[{'symbol': 'AAPL'}]),
                     build_watchlists_for_universe=mock.Mock(
                         return_value=({}, {}, {'NVDA': {'rank': 1}}))), \
         mock.patch('scripts.run_eod_sim_us.alerts.send_alert') as alert:
        eod_main()
    assert not alert.called


@mock.patch('scripts.run_eod_sim_us.time.sleep')
def test_sim2_watchlist_is_capped(mock_sleep):
    """EOD 배치가 US Sim2 워치리스트에 상한을 적용한다.

    2026-08-26 실제 값이 930종목이었다. 장중 루프는 워치리스트 종목마다 개별
    호출하므로 상한이 없으면 한 사이클이 잡 타임아웃(4분)을 넘긴다."""
    closes = _uptrend_closes()
    bars = _bars(closes, volume=_SIM2_ONLY_VOLUME)
    universe = [{'symbol': f'S{i}', 'name': f'Co{i}', 'market_cap': 1e9} for i in range(6)]
    with mock.patch('src.strategy.simulators.us_sim2_donchian.MAX_WATCHLIST', 4):
        _, out2, _ = build_watchlists_for_universe(
            universe, cik_map={}, fetch_ohlcv=mock.Mock(return_value=bars),
            fetch_fundamentals=mock.Mock())
    assert len(out2) == 4, f'상한이 안 걸렸다: {len(out2)}종목'


def test_main_stamps_watchlist_for_nearest_open_session():
    """장중에 배치를 돌리면 워치리스트가 **오늘치**로 찍혀 그 자리에서 쓰인다.

    next_us_trading_date를 쓰면 언제 돌리든 내일치가 되어, 고장을 고친 날
    검증할 수 없다(2026-08-26에 실제로 이걸로 하루 밀렸다)."""
    saved = {}
    with _patch_main(
            filter_universe=mock.Mock(return_value=[{'symbol': 'AAPL'}]),
            build_watchlists_for_universe=mock.Mock(return_value=({}, {}, {'NVDA': {}})),
            save_sim3_watchlist=mock.Mock(side_effect=lambda e, d: saved.update(date=d))), \
         mock.patch('scripts.run_eod_sim_us.watchlist_target_date', return_value='20260826'), \
         mock.patch('scripts.run_eod_sim_us.alerts.send_alert'):
        eod_main()
    assert saved['date'] == '20260826'


# ── 보유 종목의 청산 지표는 진입 자격과 무관하게 실려야 한다 (2026-09-15) ──────
# US Sim1의 청산 둘 중 하나(50일선 이탈)는 ma50을 **그날 워치리스트에서** 읽는다
# (us_sim1_minervini.decide_us_minervini). 그런데 워치리스트에 오르려면
# _trend_template_ok를 통과해야 하고, 그 조건 안에 `price > ma50`이 들어 있다
# (us_sim1_minervini.py:81). 즉 "50일선을 깬 종목"은 정의상 워치리스트에 못 올라
# ma50이 None이 되고, 청산 게이트가 구조적으로 발화하지 않는다.
#
# 실측(2026-09-11·14·15 db-data): US Sim1 보유 5종목 중 워치리스트에 오른 것은
# 0개, 거래 이력 전체(5건)가 BUY뿐이고 SELL이 한 건도 없다. 같은 파이프라인의
# US Sim2는 워치리스트가 300종목이라 보유 5종목이 전부 들어 있고 청산이 실제로
# 발화했다(09-11 SNDK, 09-14 MU).

@mock.patch('scripts.run_eod_sim_us.time.sleep')
def test_held_symbol_keeps_ma50_even_when_it_fails_entry_filters(mock_sleep):
    """보유 중인 종목은 진입 자격을 잃어도 ma50을 실은 항목으로 남는다."""
    closes = [round(200.0 - i * 0.2, 2) for i in range(230)]  # 하락 추세 → 템플릿 탈락
    bars = _bars(closes, volume=_SIM2_ONLY_VOLUME)
    universe = [{'symbol': 'PSX', 'name': 'Phillips 66', 'market_cap': 1e11}]
    out1, _, _ = build_watchlists_for_universe(
        universe, cik_map={'PSX': '0000000002'},
        fetch_ohlcv=mock.Mock(return_value=bars),
        fetch_fundamentals=mock.Mock(),
        sim1_held={'PSX'})

    assert 'PSX' in out1, '보유 종목이 워치리스트에서 빠져 50일선 이탈 청산이 영영 안 된다'
    entry = out1['PSX']
    assert entry['ma50'] == sum(closes[-50:]) / 50
    # 진입 후보로 되살아나면 안 된다 — 추세 템플릿을 통과하지 않은 종목이다.
    assert entry['pivot_price'] is None


@mock.patch('scripts.run_eod_sim_us.time.sleep')
def test_non_held_symbol_still_excluded_when_it_fails_filters(mock_sleep):
    """보유가 아니면 종전대로 탈락한다(워치리스트가 넓어지면 안 된다)."""
    closes = [round(200.0 - i * 0.2, 2) for i in range(230)]
    bars = _bars(closes, volume=_SIM2_ONLY_VOLUME)
    universe = [{'symbol': 'PSX', 'name': 'Phillips 66', 'market_cap': 1e11}]
    out1, _, _ = build_watchlists_for_universe(
        universe, cik_map={'PSX': '0000000002'},
        fetch_ohlcv=mock.Mock(return_value=bars),
        fetch_fundamentals=mock.Mock())
    assert out1 == {}


# ── US Sim4: 점수는 달이 바뀔 때만 새로 낸다 (2026-10-06) ─────────────────────
# SEC 150콜 + FINRA 한 번이라 매일 돌릴 이유가 없고, 못 냈을 때 지어낸 순위로
# 40종목을 갈아치우면 안 된다. 세 갈래(이어 쓰기 / 새로 내기 / 실패 시 보유 유지)를 고정한다.
import datetime as dt  # noqa: E402

from scripts import run_eod_sim_us as eod  # noqa: E402
from src.strategy.simulators import us_sim4_avoid as sim4  # noqa: E402


def _sim4_env(tmp_path, monkeypatch, n=160):
    monkeypatch.setattr(sim4, 'WATCHLIST_PATH', str(tmp_path / 'sim_us4_avoid_watchlist.json'))
    universe = [{'symbol': f'S{i:03d}', 'name': f'Co{i}', 'market_cap': 1e12 - i * 1e9} for i in range(n)]
    cik_map = {r['symbol']: str(i).zfill(10) for i, r in enumerate(universe)}
    volumes = {r['symbol']: 1_000_000.0 for r in universe}
    short = {r['symbol']: float(i) * 10_000 for i, r in enumerate(universe)}
    return universe, cik_map, volumes, short


def _signals(i):
    return {'accr': i * 0.001, 'issue': -i * 0.001, 'ag': 0.0, 'd_opm': 0.01, 'ni_chg': 0.02}


def test_sim4_same_month_carries_previous_list_without_network(tmp_path, monkeypatch):
    universe, cik_map, volumes, short = _sim4_env(tmp_path, monkeypatch)
    sim4.save_watchlist({'AAA': {'name': 'A', 'rank': 1, 'score': 0.9, 'market_cap': 1e12}},
                        '20261005', '202610', {'pool': 150})
    fetch_facts, fetch_short = mock.Mock(), mock.Mock()
    status = eod.refresh_sim4_watchlist(universe, cik_map, volumes, '20261006', dt.date(2026, 10, 5),
                                        fetch_facts, fetch_short, sleep=lambda s: None)
    assert status == 'carried'
    assert not fetch_facts.called and not fetch_short.called, '달이 같은데 SEC·FINRA를 쳤다'
    entries, month = sim4.load_watchlist('20261006')
    assert set(entries) == {'AAA'} and month == '202610', '날짜만 바뀌어야 한다'


def test_sim4_new_month_scores_top_pool_by_market_cap(tmp_path, monkeypatch):
    universe, cik_map, volumes, short = _sim4_env(tmp_path, monkeypatch)
    sim4.save_watchlist({'OLD': {'name': 'O', 'rank': 1, 'score': 0.9, 'market_cap': 1e12}},
                        '20261030', '202610')
    calls = []

    def fetch_facts(cik):
        calls.append(cik)
        return {'_i': int(cik)}

    with mock.patch.object(eod, 'compute_signals', side_effect=lambda facts, asof: _signals(facts['_i'])):
        status = eod.refresh_sim4_watchlist(
            universe, cik_map, volumes, '20261102', dt.date(2026, 10, 30),
            fetch_facts, lambda: ('2026-10-15', short), sleep=lambda s: None)
    assert status == 'scored'
    assert len(calls) == sim4.POOL_SIZE, '시총 상위 POOL_SIZE개만 조회해야 한다'
    entries, month = sim4.load_watchlist('20261102')
    assert month == '202611' and len(entries) == sim4.BUFFER_RANK
    assert 'OLD' not in entries
    # 시총 151위 이하는 풀에 못 든다
    assert not any(c >= 'S150' for c in entries)


def test_sim4_scoring_failure_keeps_old_month_so_the_sim_holds(tmp_path, monkeypatch):
    """공매도 잔고를 못 받으면 지난달 목록을 **옛 score_month 그대로** 이어 쓴다.
    새 달로 찍으면 심이 낡은 순위로 교체해 버린다."""
    universe, cik_map, volumes, short = _sim4_env(tmp_path, monkeypatch)
    sim4.save_watchlist({'OLD': {'name': 'O', 'rank': 1, 'score': 0.9, 'market_cap': 1e12}},
                        '20261030', '202610')
    with mock.patch.object(eod.alerts, 'send_alert') as alert:
        status = eod.refresh_sim4_watchlist(
            universe, cik_map, volumes, '20261102', dt.date(2026, 10, 30),
            mock.Mock(), mock.Mock(side_effect=RuntimeError('FINRA 503')), sleep=lambda s: None)
    assert status == 'failed' and alert.called
    entries, month = sim4.load_watchlist('20261102')
    assert set(entries) == {'OLD'} and month == '202610'


def test_sim4_thin_pool_is_a_failure_not_a_small_ranking(tmp_path, monkeypatch):
    """SEC가 대부분 실패한 날 '받은 30종목 중 상위'로 순위를 내지 않는다."""
    universe, cik_map, volumes, short = _sim4_env(tmp_path, monkeypatch)
    n = {'i': 0}

    def flaky(cik):
        n['i'] += 1
        return {'_i': int(cik)} if n['i'] % 10 == 0 else None

    with mock.patch.object(eod, 'compute_signals', side_effect=lambda facts, asof: _signals(facts['_i'])),          mock.patch.object(eod.alerts, 'send_alert') as alert:
        status = eod.refresh_sim4_watchlist(
            universe, cik_map, volumes, '20261102', dt.date(2026, 10, 30),
            flaky, lambda: ('2026-10-15', short), sleep=lambda s: None)
    assert status == 'failed' and alert.called
    assert sim4.load_watchlist('20261102') == ({}, None), '직전 목록도 없는데 뭔가 저장됐다'


def test_sim4_missing_short_interest_is_a_failure(tmp_path, monkeypatch):
    """공매도 잔고가 대부분 비면 가장 강한 신호 없이 순위를 내는 셈이다."""
    universe, cik_map, volumes, short = _sim4_env(tmp_path, monkeypatch)
    with mock.patch.object(eod, 'compute_signals', side_effect=lambda facts, asof: _signals(facts['_i'])),          mock.patch.object(eod.alerts, 'send_alert') as alert:
        status = eod.refresh_sim4_watchlist(
            universe, cik_map, volumes, '20261102', dt.date(2026, 10, 30),
            lambda cik: {'_i': int(cik)}, lambda: ('2026-10-15', {'S000': 1.0}), sleep=lambda s: None)
    assert status == 'failed' and alert.called


@mock.patch('scripts.run_eod_sim_us.time.sleep')
def test_avg_volumes_are_collected_from_bars_already_fetched(mock_sleep):
    closes = _uptrend_closes()
    bars = _bars(closes, volume=1234)
    out = {}
    build_watchlists_for_universe(
        [{'symbol': 'AAPL', 'name': 'Apple', 'market_cap': 1e9}], cik_map={},
        fetch_ohlcv=mock.Mock(return_value=bars), fetch_fundamentals=mock.Mock(), avg_volumes=out)
    assert out == {'AAPL': 1234.0}


def test_sim4_skips_other_securities_of_the_same_company(tmp_path, monkeypatch):
    """T의 상장 채권 TBB는 스크리너에 AT&T 시총을 달고 나온다. 2026-10-06 실제 실행에서
    TBB·CCZ가 상위 40에 들었다 — 회사(CIK)당 SEC 목록의 첫 티커만 보통주로 본다."""
    universe, cik_map, volumes, short = _sim4_env(tmp_path, monkeypatch)
    universe.insert(1, {'symbol': 'S000B', 'name': 'Co0 5.35% Notes', 'market_cap': 1e12})
    cik_map['S000B'] = cik_map['S000']          # 같은 회사, SEC 목록에서는 뒤에 온다
    volumes['S000B'] = 1_000.0
    short['S000B'] = 0.0
    with mock.patch.object(eod, 'compute_signals', side_effect=lambda facts, asof: _signals(facts['_i'])):
        eod.refresh_sim4_watchlist(
            universe, cik_map, volumes, '20261102', dt.date(2026, 10, 30),
            lambda cik: {'_i': int(cik)}, lambda: ('2026-10-15', short), sleep=lambda s: None)
    entries, _ = sim4.load_watchlist('20261102')
    assert 'S000B' not in entries and 'S000' in entries
