"""E9 (2026-08-04 스크래퍼 지연 재설계): run() 전체를 돌려서 실제로 상세조회가
탈락 종목에서 스킵되는지 확인한다. test_data_fetcher_threshold_order.py의 소스
순서 검증은 이 동작 검증의 보조 증거일 뿐, 여기가 실제 계약이다.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data.schemas import SyncState
from src.pipeline.workers import data_fetcher
from src.pipeline.workers.data_fetcher import DataFetcherWorker


class _FakeCtx:
    threshold = 100
    now_kst = __import__('datetime').datetime(2026, 8, 4, 11, 0)
    today_str = '20260804'
    today_display = '2026.08.04'
    scrape_pages_total = 0
    scrape_pages_failed = 0

    def log(self, msg):
        pass


def _run_with_candidates(passing_codes, failing_codes):
    ctx = _FakeCtx()
    storage = mock.MagicMock()
    storage.get_sync_files_list.return_value = []
    storage.load_sync_state.return_value = (SyncState(), {})
    storage.update_consecutive_counts.return_value = {}

    worker = DataFetcherWorker(ctx, storage)

    all_codes = passing_codes + failing_codes
    candidates = [{'code': c, 'name': f'종목{c}', 'market': 'KOSPI'} for c in all_codes]

    def fake_discussion_stats(code, today_str):
        count = 500 if code in passing_codes else 10  # threshold=100
        return {'recent_posts_count': count, 'unique_posters': 1, 'total_likes': 1,
                'new_posts': [], 'total_pages': 1, 'failed_pages': 0}

    details_calls = []

    def fake_stock_details(code):
        details_calls.append(code)
        return {'price': 10000, 'current_price': 10000}

    with mock.patch.object(data_fetcher, 'analyzer') as fake_analyzer, \
         mock.patch('src.data.adopted_registry.load', return_value={}), \
         mock.patch('src.data.sector_cache.SectorCache') as fake_sector_cache, \
         mock.patch('src.trade.auth.get_access_token', return_value='tok'), \
         mock.patch('src.trade.auth.get_base_url', return_value='https://x'), \
         mock.patch.object(worker, '_get_discussion_stats', side_effect=fake_discussion_stats), \
         mock.patch.object(worker, '_get_stock_details', side_effect=fake_stock_details), \
         mock.patch.object(data_fetcher.post_archive, 'append', return_value=0), \
         mock.patch('src.trade.kis_data_provider.KISDataProvider') as fake_kis:
        fake_analyzer.get_top_trending_stocks.side_effect = \
            lambda market: candidates if market == 'KOSPI' else []
        fake_sector_cache.return_value.ensure_fresh.return_value = None
        fake_kis.return_value.enrich_batch.side_effect = lambda rows: rows

        results = worker.run()

    return results, details_calls


def test_stock_details_skipped_for_stocks_below_threshold():
    results, details_calls = _run_with_candidates(
        passing_codes=['000001', '000002'], failing_codes=['000003', '000004', '000005'])

    assert set(details_calls) == {'000001', '000002'}, (
        '임계값 미달 종목(000003~5)의 상세조회가 호출되면 안 된다')
    assert {r.code for r in results} == {'000001', '000002'}


def test_stock_details_called_for_all_passing_stocks():
    results, details_calls = _run_with_candidates(
        passing_codes=['111111', '222222', '333333'], failing_codes=[])

    assert sorted(details_calls) == ['111111', '222222', '333333']
    assert len(results) == 3


def test_no_passing_stocks_means_zero_detail_calls():
    results, details_calls = _run_with_candidates(passing_codes=[], failing_codes=['999999'])
    assert details_calls == []
    assert results == []


def test_missing_field_log_extended_to_per_tick_power_range_history():
    """E9: 통과 종목의 결손률 로그가 open_price 외에 per·tick_power·range_history도
    본다(Success Criteria). _get_stock_details가 이 필드들을 하나도 안 채우면
    (완전 실패를 흉내) 세 필드 모두 결손 100%로 로그돼야 한다."""
    ctx = _FakeCtx()
    storage = mock.MagicMock()
    storage.get_sync_files_list.return_value = []
    storage.load_sync_state.return_value = (SyncState(), {})
    storage.update_consecutive_counts.return_value = {}
    worker = DataFetcherWorker(ctx, storage)

    candidates = [{'code': '000001', 'name': '종목1', 'market': 'KOSPI'}]

    def fake_discussion_stats(code, today_str):
        return {'recent_posts_count': 500, 'unique_posters': 1, 'total_likes': 1,
                'new_posts': [], 'total_pages': 1, 'failed_pages': 0}

    logged = []

    with mock.patch.object(data_fetcher, 'analyzer') as fake_analyzer, \
         mock.patch('src.data.adopted_registry.load', return_value={}), \
         mock.patch('src.data.sector_cache.SectorCache') as fake_sector_cache, \
         mock.patch('src.trade.auth.get_access_token', return_value='tok'), \
         mock.patch('src.trade.auth.get_base_url', return_value='https://x'), \
         mock.patch.object(worker, '_get_discussion_stats', side_effect=fake_discussion_stats), \
         mock.patch.object(worker, '_get_stock_details', return_value={'price': 10000}), \
         mock.patch.object(data_fetcher.post_archive, 'append', return_value=0), \
         mock.patch.object(worker, 'log_error', side_effect=lambda msg: logged.append(msg)), \
         mock.patch('src.trade.kis_data_provider.KISDataProvider') as fake_kis:
        fake_analyzer.get_top_trending_stocks.side_effect = \
            lambda market: candidates if market == 'KOSPI' else []
        fake_sector_cache.return_value.ensure_fresh.return_value = None
        fake_kis.return_value.enrich_batch.side_effect = lambda rows: rows

        worker.run()

    assert any('per 결손' in m for m in logged)
    assert any('tick_power 결손' in m for m in logged)
    assert any('range_history 결손' in m for m in logged)
