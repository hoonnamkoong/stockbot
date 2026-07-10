import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
from src.analyzer_5days import filter_active


def test_filters_tracked_rows():
    """추적 상태(임계값 미달) 종목은 제외한다."""
    df = pd.DataFrame([{'code': '1', '상태': '활성'}, {'code': '2', '상태': '추적'}])
    assert filter_active(df)['code'].tolist() == ['1']


def test_missing_column_treats_all_as_active():
    """2026-07-10 이전 데이터에는 상태 컬럼이 없다. 전부 활성이었다."""
    df = pd.DataFrame([{'code': '1'}, {'code': '2'}])
    assert filter_active(df)['code'].tolist() == ['1', '2']
