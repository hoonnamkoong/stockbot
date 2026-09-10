"""심2가 '오늘 하루'만 보던 외인수급 게이트에 20일 누적 판단을 얹으려면, 그 재료가
후보 딕셔너리에 있어야 한다. 같은 수급 표가 이미 거래량·외국인순매매량을 20행 주는데
지금까지 버리고 있었다 — 추가 호출 없이 20일 누적 외국인 순매매(거래량 대비 %)를
채운다(2026-08-20 KOSPI 규칙마이닝 실측 반영).

[2026-09-11] 표의 원천은 옛 item/frgn HTML → 네이버 JSON API(naver_api.investor_trend)다.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.workers.trade_engine import TradeEngineWorker


def _trend(rows):
    """[(거래량, 외인순매매)] → 수급 행, 최신이 앞."""
    return [{'date': f'202608{20 - i:02d}', 'close': 1000 + i, 'volume': v,
             'organ_net': 0, 'foreign_net': f, 'foreign_hold_ratio': 1.0}
            for i, (v, f) in enumerate(rows)]


def _enrich(trend, stock=None):
    kis = mock.MagicMock()
    kis.get_price_quote.return_value = {}
    kis.get_investor_trend_estimate.return_value = {}
    kis.get_tick_power.return_value = 0.0
    with mock.patch('src.data.naver_api.investor_trend', return_value=trend), \
         mock.patch('src.trade.kis_data_provider.KISDataProvider', return_value=kis):
        return TradeEngineWorker._enrich_universe(
            None, [stock or {'code': '005930', 'name': '테스트', 'price': 1000}])[0]


def test_frgn_net_20d_averages_the_daily_ratio():
    """거래량 100만·외인순매수 5만이 20일 내내면 하루 비율 5%, 20일 평균도 5%."""
    out = _enrich(_trend([(1_000_000, 50_000)] * 20))

    assert out['frgn_net_20d'] == 5.0


def test_frgn_net_20d_reflects_a_sell_regime():
    """20일 내내 외인 순매도였으면 평균이 음수여야 한다 — 심2가 이걸로
    '오늘은 사지만 20일 누적은 매도국면'인 노이즈를 거른다."""
    out = _enrich(_trend([(1_000_000, -60_000)] * 20))

    assert out['frgn_net_20d'] < 0


def test_frgn_net_20d_skips_zero_volume_days_without_crashing():
    """거래량 0인 날(휴장 보정 등 이례적 행)이 섞여도 죽지 않고 나머지로 평균낸다."""
    rows = [(1_000_000, 50_000)] * 19 + [(0, 0)]
    out = _enrich(_trend(rows))

    assert out['frgn_net_20d'] == 5.0


def test_existing_frgn_net_20d_is_not_overwritten():
    """스크래퍼 경로로 이미 값이 붙어 온 후보는 재조회 값으로 덮어쓰지 않는다
    (range_history와 같은 원칙)."""
    out = _enrich(_trend([(1_000_000, 50_000)] * 20),
                  {'code': '005930', 'name': 'x', 'price': 1000, 'frgn_net_20d': -99.0})

    assert out['frgn_net_20d'] == -99.0
