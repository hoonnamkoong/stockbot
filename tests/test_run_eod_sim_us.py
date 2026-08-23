from unittest import mock

from scripts.run_eod_sim_us import build_watchlist_for_universe


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


@mock.patch('scripts.run_eod_sim_us.time.sleep')
def test_build_watchlist_skips_short_history_without_fundamentals_call(mock_sleep):
    universe = [{'symbol': 'NEWCO', 'name': 'New Co', 'market_cap': 1e9}]
    fetch_ohlcv = mock.Mock(return_value=[{'close': 10.0, 'high': 10.0, 'low': 9.0}] * 30)
    fetch_fund = mock.Mock()
    out = build_watchlist_for_universe(
        universe, cik_map={'NEWCO': '0000000001'},
        fetch_ohlcv=fetch_ohlcv, fetch_fundamentals=fetch_fund)
    assert out == {}
    fetch_fund.assert_not_called()  # 추세 템플릿 탈락 종목엔 EDGAR 콜을 안 낸다


@mock.patch('scripts.run_eod_sim_us.time.sleep')
def test_build_watchlist_includes_symbol_passing_all_filters(mock_sleep):
    closes = _uptrend_with_vcp_closes()
    bars = [{'close': c, 'high': c, 'low': c} for c in closes]
    universe = [{'symbol': 'AAPL', 'name': 'Apple Inc.', 'market_cap': 3e12}]
    fetch_ohlcv = mock.Mock(return_value=bars)
    fetch_fund = mock.Mock(return_value={'eps_growth_yoy': 25.0, 'revenue_growth_yoy': 20.0})
    out = build_watchlist_for_universe(
        universe, cik_map={'AAPL': '0000320193'},
        fetch_ohlcv=fetch_ohlcv, fetch_fundamentals=fetch_fund)
    assert 'AAPL' in out
    fetch_fund.assert_called_once_with('0000320193')
    # 야후 스로틀(종목마다) + SEC EDGAR 스로틀(템플릿 통과 종목만) = 2회
    assert mock_sleep.call_count == 2


@mock.patch('scripts.run_eod_sim_us.time.sleep')
def test_build_watchlist_skips_symbol_without_cik(mock_sleep):
    closes = _uptrend_closes()
    bars = [{'close': c, 'high': c, 'low': c} for c in closes]
    universe = [{'symbol': 'NOCIK', 'name': 'No Cik', 'market_cap': 1e9}]
    fetch_ohlcv = mock.Mock(return_value=bars)
    fetch_fund = mock.Mock()
    out = build_watchlist_for_universe(
        universe, cik_map={}, fetch_ohlcv=fetch_ohlcv, fetch_fundamentals=fetch_fund)
    assert out == {}
    fetch_fund.assert_not_called()


@mock.patch('scripts.run_eod_sim_us.time.sleep')
def test_build_watchlist_survives_single_symbol_fetch_failure(mock_sleep):
    """상장폐지·티커 불일치 한 건이 배치 전체를 죽이면 그날 워치리스트가 통째로 빈다."""
    closes = _uptrend_with_vcp_closes()
    bars = [{'close': c, 'high': c, 'low': c} for c in closes]

    def fetch_ohlcv(symbol):
        if symbol == 'DEAD':
            raise RuntimeError('404 Not Found')
        return bars

    universe = [{'symbol': 'DEAD', 'name': 'Delisted Co', 'market_cap': 1e8},
                {'symbol': 'AAPL', 'name': 'Apple Inc.', 'market_cap': 3e12}]
    fetch_fund = mock.Mock(return_value={'eps_growth_yoy': 25.0, 'revenue_growth_yoy': 20.0})
    out = build_watchlist_for_universe(
        universe, cik_map={'AAPL': '0000320193'},
        fetch_ohlcv=fetch_ohlcv, fetch_fundamentals=fetch_fund)
    assert 'AAPL' in out
    assert 'DEAD' not in out
