# -*- coding: utf-8 -*-
"""수집이 실패하기 시작하면 요청을 **줄여야** 한다. 지금은 늘린다.

2026-09-08 실측. 같은 날 런들의 (총 페이지, 실패율)을 총 페이지로 정렬하면
단조증가한다:

    418→34.7%  557→17.1%  741→44.9%  999→81.7%  1285→91.4%  1473→92.0%

원인은 종료 신호가 실패를 못 견디는 것이다. `fetch_page`는 실패하면
`([], False, False)`를 준다 — `stop=False`다. 그런데 `stop`은 "어제 글 경계에
닿았다"는 **유일한** 종료 신호다. 경계가 있는 페이지가 실패하면 스캔은 멈출 줄을
모르고 max_pages(40)까지 간다. 그 부하가 다음 실패를 부르고, 그래서 또 못 멈춘다.

한 청크가 통째로 실패했다는 건 지금 못 닿는다는 뜻이다. 더 긁어도 성공하지
않고 부하만 키운다. 게다가 그렇게 모은 것은 **어차피 버려진다** —
LLMAnalyzerWorker에 `수집 실패율 초과 → 이번 런은 기록하지 않습니다` 게이트가
이미 있다.

실패를 '글 0건'으로 접지는 않는다(그건 게시글 수를 조용히 깎는다). 실패는
실패로 세고, 스캔만 멈춘다.
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
    """오늘 글로 꽉 찬 1페이지 — stop이 안 걸려 전수 스캔으로 넘어간다."""
    status_code = 200

    def __init__(self, today):
        rows = ''.join(
            f'<tr><td>{today} 09:0{i%10}</td><td></td><td>writer{i}</td>'
            f'<td></td><td>0</td><td class="title">'
            f'<a href="?nid={i}">글{i}</a></td></tr>'
            for i in range(20))
        self.text = f'<table><tbody>{rows}</tbody></table>'
        self.content = self.text.encode()


def _count_requests(monkeypatch, responder):
    calls = []

    def fake_get(self, url, **kw):
        calls.append(url)
        return responder(len(calls))

    monkeypatch.setattr(requests.Session, 'get', fake_get)
    monkeypatch.setattr(df.time, 'sleep', lambda _s: None)
    return calls


def test_청크가_통째로_실패하면_스캔을_멈춘다(worker, monkeypatch):
    """이 테스트가 잡는 것: 못 닿는 상태에서 40페이지까지 긁는 증폭."""
    def responder(_n):
        raise requests.ConnectionError('egress down')

    calls = _count_requests(monkeypatch, responder)
    worker._get_discussion_stats('005930', '2026-09-08')

    # 1페이지 순차(재시도 포함) + 첫 청크(8페이지 × 재시도)까지가 상한이다.
    # 그 뒤로도 계속 가면 40페이지분이 나간다.
    # [2026-09-09] 재시도 횟수는 이제 net이 정한다(BULK.attempts) — 호출부가
    # 숫자를 갖지 않는다. 차단기까지 겹쳐 실제 호출은 이보다 훨씬 적다.
    budget = net.BULK.attempts * (1 + df.PAGE_WORKERS)
    assert len(calls) <= budget, f'청크 전멸 뒤에도 계속 긁었다: {len(calls)}회'


def test_멈춰도_실패는_실패로_센다(worker, monkeypatch):
    """스캔을 멈춘 것이 '글이 0건이었다'로 둔갑하면 게시글 수가 조용히 깎인다."""
    def responder(_n):
        raise requests.ConnectionError('egress down')

    _count_requests(monkeypatch, responder)
    stats = worker._get_discussion_stats('005930', '2026-09-08')

    # 집계는 호출부(process_one)가 이 반환값으로 한다.
    assert stats['failed_pages'] > 0, '실패가 집계되지 않았다'
    assert stats['recent_posts_count'] == 0


def test_정상일_때는_전수_스캔이_그대로_돈다(worker, monkeypatch):
    """조기 종료가 정상 수집을 자르면 그게 더 큰 사고다."""
    today = '2026-09-08'

    def responder(_n):
        return _Res(today)

    calls = _count_requests(monkeypatch, responder)
    worker._get_discussion_stats('005930', today)

    # 오늘 글로 꽉 찬 페이지만 오므로 stop이 안 걸린다 = max_pages까지 간다.
    assert len(calls) > df.PAGE_WORKERS + 1, f'정상 경로가 잘렸다: {len(calls)}회'
