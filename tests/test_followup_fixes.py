"""후속 결함 세 건에 대한 회귀 테스트."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import requests


# ── 1. _get_discussion_stats가 죽은 updated_state를 더 이상 내지 않는다 ──

TODAY = '2026.07.10'


class _FakeResponse:
    def __init__(self, html, status_code=200):
        self.content = html.encode('utf-8')
        self.status_code = status_code


def test_discussion_stats_returns_only_live_keys(monkeypatch):
    """sync_state.stocks는 소비자가 없다. 배관을 남겨두면 db-data에 쓰레기가 배포된다."""
    from src.pipeline.workers import data_fetcher
    from src.pipeline.workers.data_fetcher import DataFetcherWorker

    old_row = (f'<tr><td>2026.07.09 23:00</td>'
               f'<td class="title"><a href="?nid=1">옛글</a></td>'
               f'<td>x</td><td>y</td><td>0</td></tr>')

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=None):
            return _FakeResponse(f'<table class="type2">{old_row}</table>')

    monkeypatch.setattr(data_fetcher.requests, 'Session', FakeSession)
    monkeypatch.setattr(data_fetcher.time, 'sleep', lambda *_: None)

    stats = object.__new__(DataFetcherWorker)._get_discussion_stats('002990', TODAY)

    assert set(stats) == {'recent_posts_count', 'new_posts', 'total_pages', 'failed_pages'}


# ── 2. adopted_registry.save()는 원자적이어야 한다 ──

@pytest.fixture
def chdir_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_save_failure_leaves_previous_file_intact(chdir_tmp, monkeypatch):
    """쓰기 도중 죽어도 기존 레지스트리가 반쪽 파일로 남으면 안 된다."""
    from src.data import adopted_registry as reg

    reg.save('20260710', {'002990': {'name': '금호건설'}})

    def boom(*a, **kw):
        raise OSError('디스크 가득 참')

    monkeypatch.setattr(reg.json, 'dump', boom)
    with pytest.raises(OSError):
        reg.save('20260710', {'002990': {'name': '금호건설'}, '065170': {'name': '비엘팜텍'}})

    # 기존 파일이 그대로 살아 있어야 한다
    assert reg.load('20260710') == {'002990': {'name': '금호건설'}}


def test_save_leaves_no_temp_file_behind(chdir_tmp):
    from src.data import adopted_registry as reg

    reg.save('20260710', {'002990': {'name': '금호건설'}})
    leftovers = [f for f in os.listdir('data') if f != 'daily_adopted.json']
    assert leftovers == []


# ── 3. fetch_kospi_top100 의 KIS 호출은 일시적 장애에 재시도한다 ──

@pytest.fixture
def kospi_module(monkeypatch):
    monkeypatch.setenv('KIS_APP_KEY', 'k')
    monkeypatch.setenv('KIS_APP_SECRET', 's')
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scratch'))
    for name in ('fetch_kospi_top100',):
        sys.modules.pop(name, None)
    import fetch_kospi_top100 as m
    monkeypatch.setattr(m.time, 'sleep', lambda *_: None)
    return m


def test_with_retry_recovers_from_connect_timeout(kospi_module):
    """2026-07-10 마감 후 런이 KIS 커넥트 타임아웃 한 번에 죽었다."""
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise requests.ConnectTimeout('connect timeout=10')
        return 'ok'

    assert kospi_module._with_retry(flaky) == 'ok'
    assert len(calls) == 3


def test_with_retry_reraises_after_exhausting(kospi_module):
    def always_fail():
        raise requests.ConnectTimeout('connect timeout=10')

    with pytest.raises(requests.ConnectTimeout):
        kospi_module._with_retry(always_fail)
