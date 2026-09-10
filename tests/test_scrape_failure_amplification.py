# -*- coding: utf-8 -*-
"""수집이 실패하기 시작하면 요청을 **줄여야** 한다.

2026-09-08 실측. 같은 날 런들의 (총 페이지, 실패율)을 총 페이지로 정렬하면
단조증가했다:

    418→34.7%  557→17.1%  741→44.9%  999→81.7%  1285→91.4%  1473→92.0%

원인은 종료 신호가 실패를 못 견디는 것이었다. 옛 `fetch_page`는 실패하면
`stop=False`를 줬는데, `stop`은 "어제 글 경계에 닿았다"는 **유일한** 종료 신호였다.
경계가 있는 페이지가 실패하면 스캔은 멈출 줄을 모르고 max_pages(40)까지 갔다.

[2026-09-11] 종토방이 커서 페이지(네이버 JSON API)가 되면서 이 증폭은 구조적으로
생길 수 없다 — 실패한 페이지는 다음 커서를 주지 않으므로 거기서 멈춘다. 그 성질을
여기서 고정한다. 실패를 '글 0건'으로 접지 않는 것도 그대로다 — 그렇게 모은 것은
LLMAnalyzerWorker의 `수집 실패율 초과 → 기록하지 않습니다` 게이트가 판정한다.
"""
import os
import sys
from unittest import mock

import pytest
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core import net
from src.pipeline.workers import data_fetcher as df
from src.pipeline.workers.data_fetcher import DataFetcherWorker

TODAY = '2026-09-08'


@pytest.fixture
def worker():
    ctx = mock.Mock()
    ctx.scrape_pages_total = 0
    ctx.scrape_pages_failed = 0
    w = DataFetcherWorker(ctx, storage=mock.Mock())
    w.log = lambda *a: None
    w.log_error = lambda *a: None
    return w


class _Res:
    """오늘 글로 꽉 찬 페이지 — 어제 경계가 없어 다음 커서로 넘어간다."""
    status_code = 200

    def __init__(self, n):
        self._n = n

    def json(self):
        posts = [{'id': f'{self._n}-{i}', 'writtenAt': f'{TODAY}T09:00:00', 'title': '글',
                  'recommendCount': 0, 'writer': {'profileId': f'w{i}'}} for i in range(20)]
        return {'result': {'posts': posts, 'lastOffset': f'c{self._n}'}}


def _count_requests(monkeypatch, responder):
    calls = []

    def fake_get(self, url, **kw):
        calls.append(url)
        return responder(len(calls))

    monkeypatch.setattr(requests.Session, 'get', fake_get)
    monkeypatch.setattr(df.time, 'sleep', lambda _s: None)
    return calls


def test_못_닿으면_첫_페이지에서_멈춘다(worker, monkeypatch):
    """이 테스트가 잡는 것: 못 닿는 상태에서 상한까지 긁는 증폭."""
    def responder(_n):
        raise requests.ConnectionError('egress down')

    calls = _count_requests(monkeypatch, responder)
    worker._get_discussion_stats('005930', TODAY)

    # 첫 페이지 한 장의 재시도(net이 정한다)가 전부다.
    assert len(calls) <= net.SCRAPE.attempts, f'못 닿는데 계속 긁었다: {len(calls)}회'


def test_멈춰도_실패는_실패로_센다(worker, monkeypatch):
    """스캔을 멈춘 것이 '글이 0건이었다'로 둔갑하면 게시글 수가 조용히 깎인다."""
    def responder(_n):
        raise requests.ConnectionError('egress down')

    _count_requests(monkeypatch, responder)
    stats = worker._get_discussion_stats('005930', TODAY)

    # 집계는 호출부(process_one)가 이 반환값으로 한다.
    assert stats['failed_pages'] == 1, '실패가 집계되지 않았다'
    assert stats['recent_posts_count'] == 0


def test_정상일_때는_상한까지_간다(worker, monkeypatch):
    """조기 종료가 정상 수집을 자르면 그게 더 큰 사고다."""
    calls = _count_requests(monkeypatch, _Res)
    worker._get_discussion_stats('005930', TODAY)

    assert len(calls) == df.DISCUSSION_MAX_PAGES, f'정상 경로가 잘렸다: {len(calls)}회'
