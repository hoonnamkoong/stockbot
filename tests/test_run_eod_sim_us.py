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
