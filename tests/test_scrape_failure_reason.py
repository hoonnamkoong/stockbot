# -*- coding: utf-8 -*-
"""수집 실패의 **이유**를 남긴다. 지금은 예외를 통째로 버린다.

2026-09-08에 스크래퍼 페이지 수집 실패율이 7%~92%로 널뛰었는데, 로그에 남은
것은 실패 **횟수**뿐이었다. `fetch_page`의 `except requests.RequestException:`이
예외 객체를 받지도 않고 버린다. 그래서 429(유량 제한)인지, 커넥션 리셋인지,
타임아웃인지를 알 수 없다 — 셋은 대응이 전혀 다르다.

집(가정용 IP)에서 같은 URL에 동시 16으로 32건을 던지면 32건 전부 HTTP 200이다.
즉 네이버 전면 차단이 아니라 GitHub 러너 egress 쪽 문제인데, **어떤 모양인지는
러너 로그가 있어야 안다.**

이유를 모르는 채 동시성이나 재시도를 건드리면 짐작으로 고치는 것이다. 먼저 센다.
(같은 판단을 PR #98이 스테이지 소요에 대해 했고, 그 값이 다음 날 KIS 차단기의
근거가 됐다.)
"""
import os
import sys
from unittest import mock

import pytest
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.workers import data_fetcher as df
from src.pipeline.workers.data_fetcher import DataFetcherWorker


@pytest.fixture
def worker():
    ctx = mock.Mock()
    w = DataFetcherWorker(ctx, storage=mock.Mock())
    w.log = lambda *a: None
    w.log_error = lambda *a: None
    return w


def _responder(monkeypatch, fn):
    monkeypatch.setattr(requests.Session, 'get', lambda self, url, **kw: fn())
    monkeypatch.setattr(df.time, 'sleep', lambda _s: None)


def test_연결_실패는_예외_이름으로_남는다(worker, monkeypatch):
    def boom():
        raise requests.ConnectionError('egress down')

    _responder(monkeypatch, boom)
    stats = worker._get_discussion_stats('005930', '2026-09-08')

    assert 'ConnectionError' in stats['failure_reasons']
    assert stats['failure_reasons']['ConnectionError'] > 0


def test_타임아웃은_연결_실패와_구분된다(worker, monkeypatch):
    """대응이 다르다 — 리셋은 유량, 타임아웃은 느림이다."""
    def boom():
        raise requests.Timeout('too slow')

    _responder(monkeypatch, boom)
    stats = worker._get_discussion_stats('005930', '2026-09-08')

    assert 'Timeout' in stats['failure_reasons']
    assert 'ConnectionError' not in stats['failure_reasons']


def test_HTTP_상태코드는_숫자로_남는다(worker, monkeypatch):
    """429인지 503인지가 유량 제한 판정의 핵심이다. 'HTTPError'로 뭉뜽그리면 못 쓴다."""
    class _R:
        status_code = 429
        text = ''
        content = b''

    _responder(monkeypatch, lambda: _R())
    stats = worker._get_discussion_stats('005930', '2026-09-08')

    assert 'HTTP 429' in stats['failure_reasons'], stats['failure_reasons']


def test_성공하면_이유가_비어_있다(worker, monkeypatch):
    class _R:
        status_code = 200
        text = '<table><tbody></tbody></table>'
        content = text.encode()

    _responder(monkeypatch, lambda: _R())
    stats = worker._get_discussion_stats('005930', '2026-09-08')

    assert stats['failure_reasons'] == {}


# ── 이유가 사람에게 도달하는가 ────────────────────────────────────────
# 카운터에 담기기만 하고 로그에 안 나가면 없는 계측과 같다.

def test_이유_요약은_많은_순으로_붙는다():
    out = df.format_failure_reasons({'ConnectionError': 3, 'HTTP 429': 12, 'Timeout': 1})
    assert out == 'HTTP 429 12, ConnectionError 3, Timeout 1', out


def test_이유가_없으면_빈_문자열이다():
    """실패가 0건인 런에 빈 괄호가 붙으면 로그가 지저분해진다."""
    assert df.format_failure_reasons({}) == ''


def test_이유_합계는_실패_건수와_맞는다(worker, monkeypatch):
    """안 맞으면 읽는 사람이 어느 쪽이 맞는지 다시 물어야 한다.

    전수 스캔 분기에서 순차로 먼저 던지는 1페이지가 total/failed에 안 세어지고
    있었다(stop이 걸린 분기에서는 세어진다). 이유 카운터는 그걸 세므로
    '실패 16인데 이유 18'처럼 어긋났다."""
    def boom():
        raise requests.ConnectionError('egress down')

    _responder(monkeypatch, boom)
    stats = worker._get_discussion_stats('005930', '2026-09-08')

    assert sum(stats['failure_reasons'].values()) == stats['failed_pages'], stats
