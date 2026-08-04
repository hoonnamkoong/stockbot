"""E9 (2026-08-04 스크래퍼 지연 재설계): 임계값 판정을 상세조회보다 먼저.

이전엔 41종목 전부 상세조회(HTTP 3회: frgn.naver·KIS inquire-price·main.naver
호가)한 뒤에야 게시글 수로 통과/폐기를 갈랐다 — 2026-08-04 실측 17개만 통과,
24개의 상세조회(72콜)가 순수 낭비였다. 두 조회는 서로 다른 소스라 순서를
바꿔도 결과가 갈리지 않는다.

DataFetcherWorker.run() 전체를 목업하는 대신, process_one의 실제 소스 순서를
검증한다 — _get_discussion_stats 호출이 _get_stock_details 호출보다 앞서고,
탈락 종목은 _get_stock_details가 아예 호출되지 않아야 한다.
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers import data_fetcher
from src.pipeline.workers.data_fetcher import DataFetcherWorker, classify


def test_discussion_stats_called_before_stock_details_in_source():
    """소스 순서 자체를 고정한다 — process_one은 run() 안의 클로저라 직접
    호출할 수 없으므로, 리팩터링이 순서를 도로 뒤집는 것을 소스 위치로 잡는다."""
    src = inspect.getsource(DataFetcherWorker.run)
    idx_discuss = src.index('self._get_discussion_stats(')
    idx_details = src.index('self._get_stock_details(')
    assert idx_discuss < idx_details, (
        '_get_discussion_stats가 _get_stock_details보다 먼저 호출돼야 한다 — '
        '임계값 미달 종목의 상세조회(HTTP 3회)를 건너뛰기 위한 순서다')


def test_status_check_happens_before_stock_details_call():
    """classify() 호출(→ status is None 조기 반환)이 _get_stock_details 호출보다
    소스상 앞에 있어야 한다 — 그래야 탈락 종목이 상세조회를 아예 안 탄다."""
    src = inspect.getsource(DataFetcherWorker.run)
    idx_classify = src.index('classify(count,')
    idx_details = src.index('self._get_stock_details(')
    assert idx_classify < idx_details


def test_classify_unaffected_by_reorder():
    """순서 변경과 무관하게 classify() 자체의 판정 로직은 그대로여야 한다."""
    assert classify(count=200, threshold=120, adopted=set(), code='X') == '활성'
    assert classify(count=50, threshold=120, adopted=set(), code='X') is None
    assert classify(count=50, threshold=120, adopted={'X'}, code='X') == '추적'
