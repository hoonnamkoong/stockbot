"""수집 신뢰성: 페이지 실패를 삼키지 않고, 반쪽 런은 저장하지 않는다."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import requests

from src.core import net
from src.pipeline.workers import data_fetcher
from src.pipeline.workers import llm_analyzer
from src.pipeline.workers.data_fetcher import DataFetcherWorker
from src.pipeline.workers.llm_analyzer import LLMAnalyzerWorker

TODAY = '2026.07.10'


@pytest.fixture(autouse=True)
def chdir_tmp(tmp_path, monkeypatch):
    """레지스트리 저장이 실제 repo data/를 오염시키지 않도록 임시 CWD로 격리한다."""
    monkeypatch.chdir(tmp_path)


def _post(nid, writer='x', day='2026-07-10'):
    return {'id': str(nid), 'writtenAt': f'{day}T09:00:00', 'title': '글',
            'recommendCount': 3, 'writer': {'profileId': writer}}


def page_json(post_nids, trailing_old_row=False):
    """종토방 JSON 한 페이지(naver_api.discussion_page가 읽는 모양)."""
    posts = [_post(nid) for nid in post_nids]
    if trailing_old_row:
        posts.append(_post(1, day='2026-07-09'))
    return {'result': {'posts': posts, 'lastOffset': None}}


class FakeResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body


def install_fake_session(monkeypatch, behavior):
    """behavior(page, attempt) -> FakeResponse/페이지 dict 또는 예외를 raise.

    page는 커서 순번이다(첫 요청 1, offset=pN이면 N). 가짜 응답의 커서를 다음 순번으로
    바꿔 넣어, 테스트가 페이지를 번호로 말할 수 있게 한다."""
    attempts = {}

    def fake_get(self, url, **kw):
        page = int(url.split('offset=p')[-1]) if 'offset=p' in url else 1
        attempts[page] = attempts.get(page, 0) + 1
        r = behavior(page, attempts[page])
        res = r if isinstance(r, FakeResponse) else FakeResponse(r)
        if isinstance(res._body, dict) and isinstance(res._body.get('result'), dict):
            res._body['result']['lastOffset'] = f'p{page + 1}'
        return res

    monkeypatch.setattr(requests.Session, 'get', fake_get)
    monkeypatch.setattr(data_fetcher.time, 'sleep', lambda *_: None)
    return attempts


def stats_for(worker):
    return worker._get_discussion_stats('002990', TODAY)


@pytest.fixture
def worker():
    return object.__new__(DataFetcherWorker)


def test_page_timeout_is_retried_then_succeeds(worker, monkeypatch):
    """1페이지가 타임아웃해도 남은 시도에서 글을 건져야 한다."""
    # [2026-09-09] 재시도 횟수는 `net`이 정한다(SCRAPE.attempts) — 호출부가
    # 숫자를 갖지 않는 것이 재편의 요점이라, 테스트도 숫자를 박지 않는다.
    # 예전엔 3을 적어 뒀고, 등급이 2로 정하자 이 테스트만 조용히 의미가 달라졌다.
    def behavior(page, attempt):
        if page == 1:
            if attempt < net.SCRAPE.attempts:
                raise requests.ReadTimeout('timeout')
            return page_json(['101', '102'], trailing_old_row=True)
        return page_json([], trailing_old_row=True)

    attempts = install_fake_session(monkeypatch, behavior)
    stats = stats_for(worker)

    assert stats['recent_posts_count'] == 2
    assert attempts[1] == net.SCRAPE.attempts
    assert stats['failed_pages'] == 0


def test_failed_page_is_reported_not_counted_as_zero(worker, monkeypatch):
    """재시도를 모두 소진한 페이지는 '글 0건'이 아니라 실패로 집계돼야 한다."""
    def behavior(page, attempt):
        raise requests.ReadTimeout('timeout')

    install_fake_session(monkeypatch, behavior)
    stats = stats_for(worker)

    assert stats['failed_pages'] >= 1
    assert stats['total_pages'] >= stats['failed_pages']


def test_rate_limited_page_is_a_failure_not_an_empty_page(worker, monkeypatch):
    """429 응답은 '글 0건'처럼 보일 수 있다. 실패로 세야 한다."""
    def behavior(page, attempt):
        return FakeResponse({}, status_code=429)

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
def _page_with_writers(pairs):
    """[(nid, 글쓴이)] → 종토방 JSON 한 페이지 + 어제 글 하나(경계)."""
    posts = [_post(nid, writer=writer) for nid, writer in pairs]
    posts.append(_post(1, day='2026-07-09'))
    return {'result': {'posts': posts, 'lastOffset': None}}


def test_unique_posters_counts_distinct_writers(worker, monkeypatch):
    """도배(한 사람이 3글)와 관심(3명이 1글씩)을 구분해야 심8의 군중축이 의미를 갖는다."""
    def behavior(page, attempt):
        return _page_with_writers([('101', '갑'), ('102', '갑'), ('103', '을')])

    install_fake_session(monkeypatch, behavior)
    stats = stats_for(worker)

    assert stats['recent_posts_count'] == 3
    assert stats['unique_posters'] == 2


def test_writer_does_not_leak_into_posts(worker, monkeypatch):
    """posts는 엑셀·LLM 프롬프트로 흘러간다. 필요 없는 필드를 실어 보내지 않는다."""
    def behavior(page, attempt):
        return _page_with_writers([('101', '갑')])

    install_fake_session(monkeypatch, behavior)
    stats = stats_for(worker)

    assert stats['new_posts'] and all('writer' not in p for p in stats['new_posts'])
    assert all(set(p) == {'nid', 'title', 'likes'} for p in stats['new_posts'])
