"""가격 이력 계약 — 두 생산자(스크래퍼 경로·심 자체 유니버스 경로)가 날짜를 보존한다.

네이버 응답은 날짜를 이미 주는데 생산자가 버려 이력이 날짜 없는 list[float]였다.
종가는 25행(당일을 빼고도 20일 채널이 서도록), 수급 계열은 이름대로 20행에 고정한다.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.workers import data_fetcher
from src.pipeline.workers.data_fetcher import DataFetcherWorker
from src.pipeline.workers.trade_engine import TradeEngineWorker
from src.strategy.simulators.base_simulator import hist_fingerprint


def _rows(n=25):
    """최신이 앞(날짜 내림차순). 행마다 값이 달라 창 길이가 값에 드러난다."""
    return [{'date': f'202611{28 - i:02d}' if i < 28 else f'202610{56 - i:02d}',
             'close': 1000 + i, 'volume': 100 * (i + 1),
             'organ_net': 10 * (i + 1), 'foreign_net': 7 * (i + 1),
             'foreign_hold_ratio': 3.0 + i * 0.1} for i in range(n)]


def _run_fetcher(rows):
    calls = []

    def fake(code, **kw):
        calls.append(kw)
        return rows
    w = object.__new__(DataFetcherWorker)
    w.kis = None
    with mock.patch.object(data_fetcher.naver_api, 'investor_trend', fake), \
         mock.patch.object(data_fetcher.naver_api, 'asking_price', lambda code, **kw: None):
        return w._get_stock_details('005930'), calls


def _run_engine(rows):
    calls = []

    def fake(code, **kw):
        calls.append(kw)
        return rows
    kis = mock.MagicMock()
    kis.get_price_quote.return_value = {}
    kis.get_investor_trend_estimate.return_value = {}
    kis.get_tick_power.return_value = 0.0
    with mock.patch('src.data.naver_api.investor_trend', fake), \
         mock.patch('src.trade.kis_data_provider.KISDataProvider', return_value=kis):
        out = TradeEngineWorker._enrich_universe(
            None, [{'code': '005930', 'name': '테스트', 'price': 1000}])[0]
    return out, calls


def _both(rows):
    return {'fetcher': _run_fetcher(rows), 'engine': _run_engine(rows)}


def test_both_producers_request_25_rows():
    """종가 이력이 25행이어야 당일을 빼고도 20일 채널이 선다."""
    for name, (_, calls) in _both(_rows()).items():
        assert [c.get('days') for c in calls] == [25], name


def test_price_history_is_dated_and_oldest_first():
    for name, (out, _) in _both(_rows()).items():
        h = out['price_history']
        assert len(h) == 25, name
        assert h[0]['date'] < h[-1]['date'], name
        assert [r['date'] for r in h] == sorted(r['date'] for r in h), name
        assert h[-1] == {'date': '20261128', 'close': 1000}, name


def test_close_none_rows_are_left_out():
    rows = _rows()
    # naver_api가 close 없는 행을 이미 거르므로 실제론 방어선이다. 아래 구 계열이 close×volume을
    # 곱하다 죽지 않게 volume도 비운다 — 여기서 보는 건 price_history가 그 행을 빼는지뿐.
    rows[3]['close'] = None
    rows[3]['volume'] = None
    for name, (out, _) in _both(rows).items():
        assert len(out['price_history']) == 24, name
        assert all(r['close'] is not None for r in out['price_history']), name


def test_supply_series_still_use_first_20_rows():
    """수급 창이 25일로 넓어지면 심2·심9-1 신호 분포가 조용히 바뀐다."""
    rows = _rows()
    f, _ = _run_fetcher(rows)
    assert len(f['amount_history']) == 20
    assert len(f['range_history']) == 20
    assert f['amount_history'] == [r['close'] * r['volume'] for r in rows[:20]][::-1]

    e, _ = _run_engine(rows)
    first = rows[:20]
    assert e['frgn_net_20d'] == sum(r['foreign_net'] / r['volume'] * 100 for r in first) / 20
    assert e['orgn_net_20d'] == sum(r['organ_net'] / r['volume'] * 100 for r in first) / 20
    assert e['amount_ma20'] == sum(r['close'] * r['volume'] for r in first) / 20
    assert len(e['range_history']) == 20


def test_hist_fp_present_and_matches_history():
    for name, (out, _) in _both(_rows()).items():
        assert out['hist_fp'] == hist_fingerprint(out['price_history']), name
        assert out['hist_fp'], name


def test_producers_agree():
    """같은 응답을 두 생산자에 먹이면 price_history가 같다."""
    b = _both(_rows())
    assert b['fetcher'][0]['price_history'] == b['engine'][0]['price_history']
    assert b['fetcher'][0]['hist_fp'] == b['engine'][0]['hist_fp']
