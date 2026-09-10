"""종토방은 커서 페이지다 — 어제 글에 닿거나, 커서가 끝나거나, 실패하면 멈춘다.

[2026-09-11] 옛 board.naver(page=N HTML)는 1페이지를 순차로 보고, 꽉 차면 병렬 청크로
전수 스캔했다(2026-08-11 D1). 09-10 네이버 이관 뒤 JSON API가 되면서 다음 페이지를
알려면 앞 응답의 커서(lastOffset)가 필요해졌다 — 병렬 폴백은 불가능해졌고, 한 페이지가
100글이라 필요도 없어졌다. 결손 없이 오늘 글을 끝까지 따라가는지만 본다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import requests

from src.pipeline.workers import data_fetcher as df
from src.pipeline.workers.data_fetcher import DataFetcherWorker

TODAY = '2026.07.10'


class _Res:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def _post(nid, day='2026-07-10'):
    return {'id': str(nid), 'writtenAt': f'{day}T09:00:00', 'title': f'글{nid}',
            'recommendCount': 3, 'writer': {'profileId': f'w{nid}'}}


def _page(posts, offset='next'):
    return _Res({'isSuccess': True, 'result': {'posts': posts, 'lastOffset': offset}})


def _install(monkeypatch, responder):
    calls = []

    def fake_get(self, url, **kw):
        calls.append(url)
        return responder(len(calls))

    monkeypatch.setattr(requests.Session, 'get', fake_get)
    monkeypatch.setattr(df.time, 'sleep', lambda *_: None)
    return calls


def _stats():
    return object.__new__(DataFetcherWorker)._get_discussion_stats('002990', TODAY)


def test_어제_글에_닿으면_요청_한_번으로_끝난다(monkeypatch):
    """대다수 종목은 오늘 글이 한 페이지 안에서 끝난다."""
    calls = _install(monkeypatch, lambda n: _page(
        [_post(101), _post(102), _post(1, day='2026-07-09')]))

    stats = _stats()

    assert stats['recent_posts_count'] == 2
    assert stats['total_pages'] == 1 and len(calls) == 1


def test_오늘_글로_가득하면_커서를_따라간다(monkeypatch):
    """한 페이지가 오늘 글로 꽉 차면 더 있을 수 있다 — 끊으면 게시글 수가 깎인다."""
    def responder(n):
        if n == 1:
            return _page([_post(101), _post(102), _post(103)], offset='c1')
        return _page([_post(201), _post(1, day='2026-07-09')], offset='c2')

    calls = _install(monkeypatch, responder)
    stats = _stats()

    assert stats['recent_posts_count'] == 4
    assert len(calls) == 2 and 'offset=c1' in calls[1]


def test_페이지_상한에서_멈춘다(monkeypatch):
    calls = _install(monkeypatch, lambda n: _page(
        [_post(n * 1000 + i) for i in range(3)], offset=f'c{n}'))

    stats = _stats()

    assert len(calls) == df.DISCUSSION_MAX_PAGES
    assert stats['recent_posts_count'] == 3 * df.DISCUSSION_MAX_PAGES


def test_커서가_끝나면_멈춘다(monkeypatch):
    calls = _install(monkeypatch, lambda n: _page([_post(101)], offset=None))

    assert _stats()['recent_posts_count'] == 1
    assert len(calls) == 1


def test_빈_페이지는_실패가_아니라_글_0건이다(monkeypatch):
    """글이 정말로 없는 종목(신규상장 등)은 실패로 세지 않는다."""
    _install(monkeypatch, lambda n: _page([], offset='c'))

    stats = _stats()

    assert stats['recent_posts_count'] == 0 and stats['failed_pages'] == 0


def test_두_페이지에_걸친_글은_한_번만_센다(monkeypatch):
    """커서 사이에 새 글이 올라오면 경계의 글이 다음 페이지에 다시 나온다."""
    def responder(n):
        if n == 1:
            return _page([_post(101), _post(102)], offset='c1')
        return _page([_post(102), _post(1, day='2026-07-09')])

    _install(monkeypatch, responder)

    assert _stats()['recent_posts_count'] == 2
