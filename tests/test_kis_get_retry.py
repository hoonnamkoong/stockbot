"""KIS 조회가 순간적인 연결 실패 한 번에 통째로 포기하지 않게 만든다.

2026-08-13: 스크래퍼 런 하나에서 KIS 호출 60건이 **전부** connect timeout(3초)으로
죽었다. 같은 시각 다른 러너의 trading 런은 KIS에 정상 도달했으니 KIS 전면 장애가
아니라 그 러너의 egress 문제였다. 그런데 `_get`은 한 번 던지고 실패하면 그 종목의
그 필드를 그 런에서 영영 포기한다 — blip 한 번이 곧 그 런 데이터 전량 손실이다.

여기서 고정하는 것:
  - connect 타임아웃과 read 타임아웃을 나눈다(연결은 빨리 포기, 응답은 기다린다).
  - 연결 계열 실패는 짧은 백오프로 재시도한다.
  - 재시도해도 안 되면 여전히 {}를 돌려준다 — 없는 값을 지어내지 않는다.
  - HTTP 응답이 온 실패(rt_cd != 0 등)는 재시도하지 않는다. 서버가 대답했는데
    또 던지면 유량제한만 키운다.
"""
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.trade.kis_data_provider import KISDataProvider


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(KISDataProvider, '_init_auth', lambda self: None)
    p = KISDataProvider()
    p._token = 'tok'
    p._base_url = 'https://openapi.example'
    p._app_key = 'k'
    p._app_secret = 's'
    return p


class _Res:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def _spy(monkeypatch, results):
    """results의 항목이 예외면 raise, 아니면 반환한다. 호출 인자를 기록한다."""
    calls = []

    def fake_get(url, **kwargs):
        calls.append(kwargs)
        item = results[min(len(calls) - 1, len(results) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(requests, 'get', fake_get)
    monkeypatch.setattr('src.trade.kis_data_provider.time.sleep', lambda _s: None)
    return calls


def test_connect_timeout_is_retried_and_can_succeed(provider, monkeypatch):
    """08-13의 blip이 이 경로로 흡수된다."""
    ok = _Res({'rt_cd': '0', 'output': {'stck_prpr': '5300'}})
    calls = _spy(monkeypatch, [requests.exceptions.ConnectTimeout('boom'), ok])

    body = provider._get('/u', 'TR', {})

    assert body.get('rt_cd') == '0'
    assert len(calls) == 2


def test_gives_up_after_the_retry_budget(provider, monkeypatch):
    calls = _spy(monkeypatch, [requests.exceptions.ConnectTimeout('boom')])

    assert provider._get('/u', 'TR', {}) == {}
    assert len(calls) == KISDataProvider.GET_ATTEMPTS


def test_failure_returns_empty_not_a_made_up_value(provider, monkeypatch):
    """조회 실패를 0으로 폴백하면 '측정 못 했다'가 '값이 0이다'로 위장된다."""
    _spy(monkeypatch, [requests.exceptions.ConnectionError('boom')])

    assert provider._get('/u', 'TR', {}) == {}


def test_server_answered_so_do_not_retry(provider, monkeypatch):
    """rt_cd != 0은 서버가 대답한 것이다. 다시 던지면 유량제한만 키운다."""
    calls = _spy(monkeypatch, [_Res({'rt_cd': '1', 'msg1': 'EGW00123'})])

    assert provider._get('/u', 'TR', {}) == {}
    assert len(calls) == 1


def test_http_error_is_not_retried(provider, monkeypatch):
    calls = _spy(monkeypatch, [_Res({}, status=500)])

    assert provider._get('/u', 'TR', {}) == {}
    assert len(calls) == 1


def test_connect_and_read_timeouts_are_separate(provider, monkeypatch):
    """하나의 숫자로 묶으면 '연결은 빨리 포기'와 '응답은 기다린다'를 동시에 못 한다."""
    calls = _spy(monkeypatch, [_Res({'rt_cd': '0'})])

    provider._get('/u', 'TR', {})

    assert calls[0]['timeout'] == (KISDataProvider.CONNECT_TIMEOUT,
                                  KISDataProvider.READ_TIMEOUT)


def test_explicit_timeout_still_overrides_the_read_side(provider, monkeypatch):
    """호출자가 넘기던 timeout 인자를 깨지 않는다(기존 호출부가 쓴다)."""
    calls = _spy(monkeypatch, [_Res({'rt_cd': '0'})])

    provider._get('/u', 'TR', {}, timeout=12)

    assert calls[0]['timeout'] == (KISDataProvider.CONNECT_TIMEOUT, 12)
