"""[2026-08-11, D1] 1페이지에서 오늘 글이 끝나면 그 한 번의 요청으로 멈춘다.

기존 경로는 PAGE_WORKERS=8 청크가 기본이라 1페이지에서 stop이 걸려도 나머지
7개가 이미 병렬로 발사된 뒤였다(discussion-stats-parallel-8 진단). 게시글이
적은 대다수 종목에서 종목당 최소 8요청이 순수 낭비였다.

1페이지가 꽉 찬(=오늘 글이 더 있을 수 있는) 드문 경우와, 1페이지 조회 자체가
실패한 경우는 여전히 기존 전수 병렬 스캔으로 폴백해야 한다 — 결손을 만들면
안 된다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import requests

from src.pipeline.workers import data_fetcher
from src.pipeline.workers.data_fetcher import DataFetcherWorker

TODAY = '2026.07.10'


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
            '<td class="title"><a href="/item/board_read.naver?code=1&nid=999">옛글</a></td>'
            '<td>x</td><td>y</td><td>0</td></tr>'
        )
    return f'<table class="type2">{"".join(rows)}</table>'


class FakeResponse:
    def __init__(self, html, status_code=200):
        self.content = html.encode('utf-8')
        self.status_code = status_code


def install_fake_session(monkeypatch, behavior):
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


def _worker():
    return object.__new__(DataFetcherWorker)


def test_unsaturated_first_page_costs_exactly_one_request(monkeypatch):
    """오늘 글이 1페이지 안에서 끝나는 흔한 경우 — 요청 1번으로 끝나야 한다."""
    def behavior(page, attempt):
        return page_html(['101', '102'], trailing_old_row=True)

    attempts = install_fake_session(monkeypatch, behavior)
    stats = stats_for(_worker())

    assert stats['recent_posts_count'] == 2
    assert stats['total_pages'] == 1
    assert list(attempts.keys()) == [1], f'2페이지 이상을 건드렸다: {attempts}'


def test_saturated_first_page_falls_back_to_parallel_scan(monkeypatch):
    """1페이지가 오늘 글로 꽉 차면(stop 없음) 더 있을 수 있으므로 병렬 전수 스캔으로 확장한다.

    폴백은 기존 청크(PAGE_WORKERS=8) 병렬 스캔 그대로다 — 1페이지 20개 +
    2~8페이지 각 1개(그 페이지 안에서 stop)씩 27개가 나와야 한다.
    """
    def behavior(page, attempt):
        if page == 1:
            return page_html([str(100 + i) for i in range(20)], trailing_old_row=False)
        return page_html([str(200 + page)], trailing_old_row=True)

    attempts = install_fake_session(monkeypatch, behavior)
    stats = stats_for(_worker())

    assert stats['recent_posts_count'] == 27
    assert 2 in attempts, '1페이지가 꽉 찼는데 2페이지를 안 봤다 — 결손 위험'


def test_first_page_fetch_failure_falls_back_to_parallel_scan(monkeypatch):
    """1페이지 조회 자체가 실패하면(모름) 안전하게 전수 병렬 스캔으로 폴백한다."""
    def behavior(page, attempt):
        if page == 1:
            raise requests.ReadTimeout('timeout')
        return page_html([], trailing_old_row=True)

    install_fake_session(monkeypatch, behavior)
    stats = stats_for(_worker())

    assert stats['failed_pages'] >= 1
