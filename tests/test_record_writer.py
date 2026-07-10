"""save_data 특성화 테스트.

record_writer.py 분리(순수 이동) 전에 현재 동작을 고정한다. 이동 후에도
동일하게 통과해야 한다. save_data는 analyzer 네임스페이스로도 계속 노출된다.
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime

import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def chdir_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def sample_df():
    return pd.DataFrame([
        {'종목명': '금호건설', 'code': '002990', '현재가': 17940,
         '게시물': 90, 'posts_summary': '요약', '상태': '활성'},
        {'종목명': '비엘팜텍', 'code': '065170', '현재가': 3950,
         '게시물': 70, 'posts_summary': '요약2', '상태': '추적'},
    ])


def test_save_data_empty_returns_empty_dict():
    from src.strategy.record_writer import save_data
    assert save_data(pd.DataFrame()) == {}


def test_save_data_writes_all_five_artifacts():
    from src.strategy.record_writer import save_data

    now = datetime(2026, 7, 11, 10, 0, 0)
    result = save_data(sample_df(), start_time=now)

    assert set(result) == {'csv', 'excel', 'monthly', 'snapshot'}
    assert os.path.exists('data/trending_integrated.csv')
    assert os.path.exists('data/trending_integrated.xlsx')
    assert os.path.exists('data/trending_integrated_2026-07.xlsx')
    assert os.path.exists('data/trending_integrated_20260711_10.xlsx')
    assert os.path.exists('data/latest_stocks.json')
    assert os.path.exists('data/status.json')


def test_monthly_excel_accumulates():
    from src.strategy.record_writer import save_data

    now = datetime(2026, 7, 11, 10, 0, 0)
    save_data(sample_df(), start_time=now)
    save_data(sample_df(), start_time=datetime(2026, 7, 11, 11, 0, 0))

    monthly = pd.read_excel('data/trending_integrated_2026-07.xlsx')
    assert len(monthly) == 4  # 2행 × 2런 누적


def test_latest_stocks_json_has_status_column():
    """오늘 넣은 상태 컬럼이 JSON 산출물까지 살아있어야 한다."""
    from src.strategy.record_writer import save_data

    save_data(sample_df(), start_time=datetime(2026, 7, 11, 10, 0, 0))
    rows = json.load(open('data/latest_stocks.json', encoding='utf-8'))
    assert {r['상태'] for r in rows} == {'활성', '추적'}


def test_save_data_still_exposed_via_analyzer():
    """하위 호환: analyzer.save_data 호출부(llm_analyzer, scraper_legacy)가 깨지면 안 된다."""
    from src.strategy import analyzer
    assert analyzer.save_data is not None
    result = analyzer.save_data(sample_df(), start_time=datetime(2026, 7, 11, 10, 0, 0))
    assert 'csv' in result
