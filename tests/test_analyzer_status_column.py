import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from src.strategy.analyzer import analyze_discussion_trend


@pytest.fixture(autouse=True)
def chdir_tmp(tmp_path, monkeypatch):
    # compare_with_history()가 cwd의 data/ 를 읽는다. 실제 데이터와 격리한다.
    monkeypatch.chdir(tmp_path)


def test_status_column_present():
    """상태 컬럼이 없으면 백테스트가 추적 종목을 매수 후보로 오인한다."""
    rows = [
        {'code': '111111', 'name': '활성종목', 'price': 1000, 'change_rate': '+1.00%',
         'recent_posts_count': 90, 'status': '활성'},
        {'code': '222222', 'name': '추적종목', 'price': 2000, 'change_rate': '+2.00%',
         'recent_posts_count': 70, 'status': '추적'},
    ]
    df, _ = analyze_discussion_trend(rows)
    assert '상태' in df.columns
    assert sorted(df['상태'].tolist()) == ['추적', '활성']
