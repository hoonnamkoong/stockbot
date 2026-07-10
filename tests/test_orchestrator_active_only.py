import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data.schemas import StockData
from src.pipeline.orchestrator import active_only


def test_active_only_filters_tracked():
    """추적 종목은 매수 후보로 넘어가면 안 된다."""
    stocks = [
        StockData(code='111111', name='활성종목', status='활성'),
        StockData(code='222222', name='추적종목', status='추적'),
    ]
    assert [s.code for s in active_only(stocks)] == ['111111']
