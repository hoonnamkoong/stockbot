"""Sim12의 국면별 게이트 재료: 기관 20일 누적 수급·20일 평균 거래대금·외인 보유율
5일 변화. frgn_net_20d와 같은 표에서 재활용한다(추가 호출 0).

[2026-09-11] 표의 원천은 옛 item/frgn HTML → 네이버 JSON API(naver_api.investor_trend)다."""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.workers.trade_engine import TradeEngineWorker


def _trend(rows):
    """rows: [(px, vol, orgn, frgn, hold), ...] 최신순(오늘이 0번째)."""
    return [{'date': f'202608{20 - i:02d}', 'close': r[0], 'volume': r[1],
             'organ_net': r[2], 'foreign_net': r[3], 'foreign_hold_ratio': r[4]}
            for i, r in enumerate(rows)]


def _enrich(trend, existing=None):
    kis = mock.MagicMock()
    kis.get_price_quote.return_value = {}
    kis.get_investor_trend_estimate.return_value = {}
    kis.get_tick_power.return_value = 0.0
    cand = existing or {'code': '005930', 'name': '테스트', 'price': 1000}
    with mock.patch('src.data.naver_api.investor_trend', return_value=trend), \
         mock.patch('src.trade.kis_data_provider.KISDataProvider', return_value=kis):
        return TradeEngineWorker._enrich_universe(None, [cand])[0]


def test_orgn_net_20d_averages_the_daily_ratio():
    rows = [(1000, 1_000_000, 30_000, 50_000, 46.0)] * 20
    out = _enrich(_trend(rows))

    assert out['orgn_net_20d'] == 3.0


def test_amount_ma20_is_close_times_volume_averaged():
    rows = [(1000, 1_000_000, 0, 0, 46.0)] * 20
    out = _enrich(_trend(rows))

    assert out['amount_ma20'] == 1000 * 1_000_000


def test_frgn_hold_chg_5d_is_today_minus_five_days_ago():
    # index 0(오늘)=46.0%, index 5(5거래일 전)=44.0% → +2.0%p
    rows = [(1000, 1_000_000, 0, 0, 46.0)] * 5 + [(1000, 1_000_000, 0, 0, 44.0)] * 15
    out = _enrich(_trend(rows))

    assert round(out['frgn_hold_chg_5d'], 3) == 2.0


def test_missing_fields_when_fewer_than_six_rows():
    """5일 전 값을 못 만들면(행 부족) 지어내지 않는다 — 키 자체가 없어야 한다."""
    rows = [(1000, 1_000_000, 10_000, 10_000, 46.0)] * 3
    out = _enrich(_trend(rows))

    assert 'frgn_hold_chg_5d' not in out
    assert 'orgn_net_20d' in out  # 이건 3행만 있어도 계산 가능


def test_missing_hold_ratio_is_not_fabricated():
    """보유율이 빈 날이 끼면 5일 변화를 만들지 않는다 — 0으로 채우면 '변화 없음'이 된다."""
    rows = [(1000, 1_000_000, 0, 0, 46.0)] * 5 + [(1000, 1_000_000, 0, 0, None)] * 15
    out = _enrich(_trend(rows))

    assert 'frgn_hold_chg_5d' not in out


def test_existing_values_are_not_overwritten():
    out = _enrich(_trend([(1000, 1_000_000, 30_000, 50_000, 46.0)] * 20),
                  existing={'code': '005930', 'name': 'x', 'price': 1000,
                            'orgn_net_20d': -99.0, 'amount_ma20': -1.0,
                            'frgn_hold_chg_5d': -1.0})

    assert out['orgn_net_20d'] == -99.0
    assert out['amount_ma20'] == -1.0
    assert out['frgn_hold_chg_5d'] == -1.0
