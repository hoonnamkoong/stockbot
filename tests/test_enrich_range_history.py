"""자체 유니버스를 쓰는 심도 채널을 만들 수 있어야 한다.

2026-08-13 심 전체 감사에서 심5(레인지 스윙)의 무거래 원인이 실측으로 확정됐다:

    [레인지] 진입 없음 — 채널폭 통과 19개 중
    저점에 가장 가까운 000660 저점 대비 +24.4% (기준 +3% 이내)

버즈 후보(인기·급등 종목)는 정의상 채널 저점 근처에 있을 수 없다. 그래서
유니버스를 바꿔야 하는데, **바꾸는 순간 더 나빠지는 함정**이 있었다.

`_enrich_universe`는 `sparkline_price`(5일)만 채우고 `range_history`(20일)는
채우지 않았다. `range_history`를 만드는 곳은 스크래퍼 경로
(`data_fetcher._get_stock_details`)뿐이다. 그래서 심5에 `get_universe()`를 달면
후보에 `range_history`가 없어 `_channel()`이 None을 돌려주고 **진입이 구조적으로
불가능**해진다 — 심9-1에서 실행 경로를 확인 안 하고 단정했다가 오진했던 것과
같은 계열의 함정이다.

같은 수급 표가 이미 20행을 준다. 지금까지 앞 5개만 쓰고 버렸다 — 추가 호출 없이
전부 담는다. ([2026-09-11] 표의 원천은 네이버 JSON API다 — naver_api.investor_trend)
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.workers.trade_engine import TradeEngineWorker


def _trend(n=20):
    """최신이 앞 — 가장 최근 종가 1000, 가장 오래된 종가 1000+n-1."""
    return [{'date': f'202608{n - i:02d}', 'close': 1000 + i, 'volume': 0,
             'organ_net': 0, 'foreign_net': 0, 'foreign_hold_ratio': 1.0}
            for i in range(n)]


def _enrich(trend, stock=None):
    kis = mock.MagicMock()
    kis.get_price_quote.return_value = {}
    kis.get_investor_trend_estimate.return_value = {}
    kis.get_tick_power.return_value = 0.0
    with mock.patch('src.data.naver_api.investor_trend', return_value=trend), \
         mock.patch('src.trade.kis_data_provider.KISDataProvider', return_value=kis):
        return TradeEngineWorker._enrich_universe(
            None, [stock or {'code': '005930', 'name': '테스트', 'price': 1000}])[0]


def test_range_history_is_filled_from_the_same_page():
    """이게 없으면 자체 유니버스 심은 채널을 못 만들어 영원히 못 산다."""
    out = _enrich(_trend(20))

    assert len(out.get('range_history') or []) == 20


def test_range_history_is_oldest_to_newest():
    """`_channel`과 돈치안이 마지막을 '최신'으로 읽는다. 순서가 뒤집히면
    채널 저점·고점이 조용히 반대가 된다."""
    out = _enrich(_trend(20))
    hist = out['range_history']

    assert hist[-1] == 1000, '마지막이 가장 최근 종가여야 한다'
    assert hist[0] == 1019


def test_sparkline_still_only_five_days():
    """기존 소비자(ADX 근사)를 깨지 않는다."""
    out = _enrich(_trend(20))

    assert len(out['sparkline_price']) == 5
    assert out['sparkline_price'][-1] == 1000


def test_existing_range_history_is_not_overwritten():
    """스크래퍼 경로로 들어온 후보는 이미 값을 갖고 있다. 덮어쓰면 그 런의
    수집분을 재조회 값으로 바꿔치기하게 된다."""
    out = _enrich(_trend(20), {'code': '005930', 'name': 'x', 'price': 1000,
                               'range_history': [7, 8, 9]})

    assert out['range_history'] == [7, 8, 9]


def test_unreachable_trend_leaves_fields_unset():
    """못 닿으면 채널 재료를 지어내지 않는다 — 없는 채널은 '진입 없음'이 맞다."""
    out = _enrich(None)

    assert 'range_history' not in out and 'sparkline_price' not in out
