"""수집 신뢰성: 페이지 실패를 삼키지 않고, 반쪽 런은 저장하지 않는다."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import requests

from src.pipeline.workers import data_fetcher
from src.pipeline.workers import llm_analyzer
from src.pipeline.workers.data_fetcher import DataFetcherWorker
from src.pipeline.workers.llm_analyzer import LLMAnalyzerWorker

TODAY = '2026.07.10'


@pytest.fixture(autouse=True)
def chdir_tmp(tmp_path, monkeypatch):
    """레지스트리 저장이 실제 repo data/를 오염시키지 않도록 임시 CWD로 격리한다."""
    monkeypatch.chdir(tmp_path)


def page_html(post_nids, trailing_old_row=False):
    rows = []
    for nid in post_nids:
        rows.append(
            f'<tr><td>{TODAY} 09:00</td>'
            f'<td class="title"><a href="/item/board_read.naver?code=1&nid={nid}">글</a></td>'
            f'<td>x</td><td>y</td><td>3</td></tr>'
        )
    if trailing_old_row:
        rows.append(
            '<tr><td>2026.07.09 23:00</td>'
            '<td class="title"><a href="/item/board_read.naver?code=1&nid=1">옛글</a></td>'
            '<td>x</td><td>y</td><td>0</td></tr>'
        )
    return f'<table class="type2">{"".join(rows)}</table>'


class FakeResponse:
    def __init__(self, html, status_code=200):
        self.content = html.encode('utf-8')
        self.status_code = status_code


def install_fake_session(monkeypatch, behavior):
    """behavior(page, attempt) -> FakeResponse/html 문자열 또는 예외를 raise"""
    attempts = {}

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=None):
            page = int(url.split('page=')[-1])
            attempts[page] = attempts.get(page, 0) + 1
            r = behavior(page, attempts[page])
            return r if isinstance(r, FakeResponse) else FakeResponse(r)

    monkeypatch.setattr(data_fetcher.requests, 'Session', FakeSession)
    monkeypatch.setattr(data_fetcher.time, 'sleep', lambda *_: None)
    return attempts


def stats_for(worker):
    return worker._get_discussion_stats('002990', TODAY)


@pytest.fixture
def worker():
    return object.__new__(DataFetcherWorker)


def test_page_timeout_is_retried_then_succeeds(worker, monkeypatch):
    """1페이지가 두 번 타임아웃해도 세 번째 시도에서 글을 건져야 한다."""
    def behavior(page, attempt):
        if page == 1:
            if attempt < 3:
                raise requests.ReadTimeout('timeout')
            return page_html(['101', '102'], trailing_old_row=True)
        return page_html([], trailing_old_row=True)

    attempts = install_fake_session(monkeypatch, behavior)
    stats = stats_for(worker)

    assert stats['recent_posts_count'] == 2
    assert attempts[1] == 3
    assert stats['failed_pages'] == 0


def test_failed_page_is_reported_not_counted_as_zero(worker, monkeypatch):
    """재시도를 모두 소진한 페이지는 '글 0건'이 아니라 실패로 집계돼야 한다."""
    def behavior(page, attempt):
        if page == 1:
            raise requests.ReadTimeout('timeout')
        return page_html([], trailing_old_row=True)

    install_fake_session(monkeypatch, behavior)
    stats = stats_for(worker)

    assert stats['failed_pages'] >= 1
    assert stats['total_pages'] >= stats['failed_pages']


def test_rate_limited_page_is_a_failure_not_an_empty_page(worker, monkeypatch):
    """429 응답은 파싱하면 '글 0건'처럼 보인다. 실패로 세야 한다."""
    def behavior(page, attempt):
        if page == 1:
            return FakeResponse('<html>429 Too Many Requests</html>', status_code=429)
        return page_html([], trailing_old_row=True)

    install_fake_session(monkeypatch, behavior)
    stats = stats_for(worker)

    assert stats['failed_pages'] >= 1


def test_stock_workers_are_decoupled_from_threshold():
    """동시 워커 수가 게시글 임계값(40~130)에 묶여 있으면 안 된다."""
    assert hasattr(data_fetcher, 'STOCK_WORKERS')
    assert data_fetcher.STOCK_WORKERS <= 16


# ── 반쪽 런 저장 차단 ────────────────────────────────────────────


class FakeCtx:
    today_str = '20260710'

    def __init__(self, failed, total):
        self.scrape_pages_failed = failed
        self.scrape_pages_total = total
        self.now_kst = None

    def log(self, msg):
        pass

    def scrape_degraded(self):
        from src.pipeline.context import PipelineContext
        return PipelineContext.scrape_degraded(self)


class FakeStorage:
    def __init__(self):
        self.saved = []

    def save_latest_stocks(self, stocks, now_kst):
        self.saved.append(stocks)


def make_analyzer(monkeypatch, failed, total):
    w = object.__new__(LLMAnalyzerWorker)
    w.ctx = FakeCtx(failed, total)
    w.storage = FakeStorage()
    calls = []
    monkeypatch.setattr(llm_analyzer.analyzer, 'analyze_discussion_trend',
                        lambda c: (c, None))
    monkeypatch.setattr(llm_analyzer.analyzer, 'save_data',
                        lambda df: calls.append('save_data'))
    return w, calls


def test_degraded_run_persists_nothing(monkeypatch):
    """페이지 절반이 죽은 런은 엑셀에도 대시보드에도 쓰지 않는다."""
    w, calls = make_analyzer(monkeypatch, failed=50, total=100)

    assert w._persist([{'code': '002990'}]) is False
    assert calls == []
    assert w.storage.saved == []


def test_healthy_run_persists_both(monkeypatch):
    """정상 런은 엑셀과 대시보드에 모두 기록한다."""
    w, calls = make_analyzer(monkeypatch, failed=1, total=100)

    assert w._persist([{'code': '002990'}]) is True
    assert calls == ['save_data']
    assert len(w.storage.saved) == 1


# ── [Sim8] 고유 작성자 수 ──────────────────────────────
def _rows_with_writers(pairs):
    """[(nid, 글쓴이)] → 게시판 표 HTML. 실제 컬럼 순서는 날짜/제목/글쓴이/조회/공감/비공감."""
    rows = "".join(
        f'<tr><td>{TODAY} 09:00</td>'
        f'<td class="title"><a href="/item/board_read.naver?code=1&nid={nid}">글</a></td>'
        f'<td>{writer}</td><td>1</td><td>3</td><td>0</td></tr>'
        for nid, writer in pairs
    )
    old = ('<tr><td>2026.07.09 23:00</td>'
           '<td class="title"><a href="/item/board_read.naver?code=1&nid=1">옛글</a></td>'
           '<td>x</td><td>y</td><td>0</td></tr>')
    return f'<table class="type2">{rows}{old}</table>'


def test_unique_posters_counts_distinct_writers(worker, monkeypatch):
    """도배(한 사람이 3글)와 관심(3명이 1글씩)을 구분해야 심8의 군중축이 의미를 갖는다."""
    def behavior(page, attempt):
        if page == 1:
            return _rows_with_writers([('101', '갑'), ('102', '갑'), ('103', '을')])
        return _rows_with_writers([])

    install_fake_session(monkeypatch, behavior)
    stats = stats_for(worker)

    assert stats['recent_posts_count'] == 3
    assert stats['unique_posters'] == 2


def test_writer_does_not_leak_into_posts(worker, monkeypatch):
    """posts는 엑셀·LLM 프롬프트로 흘러간다. 필요 없는 필드를 실어 보내지 않는다."""
    def behavior(page, attempt):
        if page == 1:
            return _rows_with_writers([('101', '갑')])
        return _rows_with_writers([])

    install_fake_session(monkeypatch, behavior)
    stats = stats_for(worker)

    assert stats['new_posts'] and all('writer' not in p for p in stats['new_posts'])
