import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers import data_fetcher
from src.pipeline.workers.data_fetcher import DataFetcherWorker


class FakeResponse:
    def __init__(self, html):
        self.content = html.encode('utf-8')


def make_worker():
    w = object.__new__(DataFetcherWorker)
    w._reset_body_stats()
    return w


def test_body_found_counts_as_success(monkeypatch):
    monkeypatch.setattr(data_fetcher.requests, 'get',
                        lambda url, **kw: FakeResponse('<div id="body">내용입니다</div>'))
    w = make_worker()

    assert w._get_post_body('005930', '1') == '내용입니다'
    assert w.body_ok == 1
    assert w.body_fail == 0


def test_missing_body_element_counts_as_failure(monkeypatch):
    """본문 태그가 없으면 실패다. 빈 문자열을 성공으로 세면
    '본문 없이 제목만 분석 중'인 상태가 통계에서 사라진다."""
    monkeypatch.setattr(data_fetcher.requests, 'get',
                        lambda url, **kw: FakeResponse('<div>다른 내용</div>'))
    w = make_worker()

    assert w._get_post_body('005930', '1') == ''
    assert w.body_ok == 0
    assert w.body_fail == 1


def test_request_exception_counts_as_failure(monkeypatch):
    def boom(url, **kw):
        raise RuntimeError('network down')
    monkeypatch.setattr(data_fetcher.requests, 'get', boom)
    w = make_worker()

    assert w._get_post_body('005930', '1') == ''
    assert w.body_fail == 1


def test_counts_accumulate_across_calls(monkeypatch):
    htmls = ['<div id="body">A</div>', '<div>없음</div>', '<div id="body">C</div>']
    it = iter(htmls)
    monkeypatch.setattr(data_fetcher.requests, 'get',
                        lambda url, **kw: FakeResponse(next(it)))
    w = make_worker()

    for i in range(3):
        w._get_post_body('005930', str(i))

    assert (w.body_ok, w.body_fail) == (2, 1)
