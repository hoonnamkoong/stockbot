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
