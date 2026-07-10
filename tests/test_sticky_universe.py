import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from src.data.schemas import StockData


def test_stockdata_defaults_to_active():
    s = StockData(code='002990', name='금호건설')
    assert s.status == '활성'


def test_classify_active_when_threshold_met():
    from src.pipeline.workers.data_fetcher import classify
    assert classify(count=90, threshold=80, adopted=set()) == '활성'


def test_classify_tracked_when_adopted_but_below_threshold():
    """9시에 채택된 종목은 11시 임계값을 못 넘겨도 리스트에 남는다."""
    from src.pipeline.workers.data_fetcher import classify
    assert classify(count=70, threshold=80, adopted={'002990'}, code='002990') == '추적'


def test_classify_drops_unadopted_below_threshold():
    from src.pipeline.workers.data_fetcher import classify
    assert classify(count=70, threshold=80, adopted=set(), code='002990') is None


def test_classify_active_when_count_equals_threshold():
    """count == threshold 경계값도 신규 채택으로 봐야 한다."""
    from src.pipeline.workers.data_fetcher import classify
    assert classify(count=80, threshold=80, adopted=set(), code='x') == '활성'


def test_merge_universe_appends_missing_adopted_stock():
    """거래량 상위에 없는 채택 종목은 이름/시장 정보와 함께 뒤에 추가돼야 한다."""
    from src.pipeline.workers.data_fetcher import merge_universe
    trending = [{'code': '000001', 'name': '가나다', 'market': 'KOSPI'}]
    adopted = {'002990': {'name': '금호건설', 'market': 'KOSPI'}}

    result = merge_universe(trending, adopted)

    assert result == [
        {'code': '000001', 'name': '가나다', 'market': 'KOSPI'},
        {'code': '002990', 'name': '금호건설', 'market': 'KOSPI'},
    ]


def test_merge_universe_does_not_duplicate_already_trending_stock():
    """채택 종목이 이미 거래량 상위에 있으면 중복 추가하지 않는다."""
    from src.pipeline.workers.data_fetcher import merge_universe
    trending = [{'code': '002990', 'name': '금호건설', 'market': 'KOSPI'}]
    adopted = {'002990': {'name': '금호건설', 'market': 'KOSPI'}}

    result = merge_universe(trending, adopted)

    assert result == [{'code': '002990', 'name': '금호건설', 'market': 'KOSPI'}]


def test_merge_universe_empty_adopted_leaves_trending_unchanged():
    """당일 채택 종목이 없으면 거래량 상위 목록을 그대로 반환한다."""
    from src.pipeline.workers.data_fetcher import merge_universe
    trending = [{'code': '000001', 'name': '가나다', 'market': 'KOSPI'}]

    result = merge_universe(trending, {})

    assert result == trending
