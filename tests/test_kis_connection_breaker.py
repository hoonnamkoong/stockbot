"""egress가 죽었으면 종목마다 다시 물어보지 않는다.

2026-09-08 실측. 실전매매 런 네 개가 잡 타임아웃(3분)에 잘려 텔레그램 실패
알림이 나갔다. PR #98이 넣어둔 구간 계측이 값을 남겼는데, 네 런이 거의 동일했다:

    자체 유니버스 수집            50.0 / 50.0 / 50.2 / 49.7초
    자체 유니버스 공유 보강       32.2 / 32.3 / 31.9 / 32.3초
    KIS 블라인드 보강(5종목)      50.1 / 49.9 / 50.0 / 50.0초

50초는 꼬리가 길어진 값이 아니라 **상수**다. 한 호출의 재시도 예산이
3 + 0.3 + 3 + 0.6 + 3 = 9.9초이고, 5종목이면 49.5초 — 실측과 맞는다.
egress가 죽으면 첫 종목에서 이미 답이 나왔는데도 나머지를 전부 같은 값으로
다시 물어보기 때문이다.

그래서 **연결 실패가 연속으로 예산을 다 태우면 그 프로세스에서 재시도를
멈춘다.** 반환값은 지금과 같은 {}다 — 없는 값을 지어내지 않는다는 성질은
그대로고, 같은 결론에 더 빨리 도달할 뿐이다.

차단기는 클래스 레벨이다. program_trader가 "새 인스턴스 = 캐시 무시"로 매번
새 KISDataProvider를 만들기 때문에, 인스턴스 상태로 두면 한 번도 안 걸린다.
"""
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.trade.kis_data_provider import KISDataProvider


@pytest.fixture(autouse=True)
def _reset_breaker(monkeypatch):
    monkeypatch.setattr(KISDataProvider, '_conn_fail_streak', 0, raising=False)


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(KISDataProvider, '_init_auth', lambda self: None)
    p = KISDataProvider()
    p._token = 'tok'
    p._base_url = 'https://openapi.example'
    return p


class _Res:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def _spy(monkeypatch, results):
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


def test_연결이_계속_죽으면_이후_호출은_요청을_안_낸다(provider, monkeypatch):
    """이 테스트가 잡는 것: 5종목×9.9초=50초를 태우던 구간이 임계 뒤로는 0초가 된다."""
    calls = _spy(monkeypatch, [requests.exceptions.ConnectTimeout('boom')])

    for _ in range(KISDataProvider.CONN_BREAKER_STREAK):
        provider._get('/u', 'TR', {})
    burned = len(calls)

    # 임계를 넘긴 뒤의 호출은 네트워크를 건드리지 않는다.
    assert provider._get('/u', 'TR', {}) == {}
    assert len(calls) == burned


def test_임계_전까지는_평소대로_재시도한다(provider, monkeypatch):
    """blip 한 번에 그 런의 KIS를 통째로 끄면 2026-08-13 회귀다."""
    calls = _spy(monkeypatch, [requests.exceptions.ConnectTimeout('boom')])

    provider._get('/u', 'TR', {})

    assert len(calls) == KISDataProvider.GET_ATTEMPTS


def test_한_번_닿으면_차단기가_풀린다(provider, monkeypatch):
    """연속이 아니면 장애가 아니다. 성공은 egress가 살아 있다는 증거다."""
    boom = requests.exceptions.ConnectTimeout('boom')
    _spy(monkeypatch, [boom, boom, boom, _Res({'rt_cd': '0'})])

    provider._get('/u', 'TR', {})                       # 예산 소진 1회
    assert KISDataProvider._conn_fail_streak == 1       # 소진이 세어졌나

    assert provider._get('/u', 'TR', {}).get('rt_cd') == '0'
    assert KISDataProvider._conn_fail_streak == 0       # 닿았으니 풀렸나


def test_서버가_대답한_실패는_차단기를_올리지_않는다(provider, monkeypatch):
    """rt_cd != 0은 연결이 됐다는 뜻이다. 이걸 세면 멀쩡한 egress를 끊는다."""
    _spy(monkeypatch, [_Res({'rt_cd': '1', 'msg1': 'EGW00123'})])

    for _ in range(KISDataProvider.CONN_BREAKER_STREAK + 1):
        provider._get('/u', 'TR', {})

    assert KISDataProvider._conn_fail_streak == 0


def test_차단된_동안에도_값을_지어내지_않는다(provider, monkeypatch):
    """빠르게 실패하는 것과 0을 돌려주는 것은 다르다."""
    _spy(monkeypatch, [requests.exceptions.ConnectTimeout('boom')])

    for _ in range(KISDataProvider.CONN_BREAKER_STREAK):
        provider._get('/u', 'TR', {})

    assert provider._get('/u', 'TR', {}) == {}


def test_차단기는_인스턴스를_넘어_공유된다(monkeypatch):
    """program_trader는 매 호출 새 인스턴스를 만든다 — 인스턴스 상태면 안 걸린다."""
    monkeypatch.setattr(KISDataProvider, '_init_auth', lambda self: None)
    calls = _spy(monkeypatch, [requests.exceptions.ConnectTimeout('boom')])

    for _ in range(KISDataProvider.CONN_BREAKER_STREAK):
        p = KISDataProvider()
        p._token, p._base_url = 'tok', 'https://openapi.example'
        p._get('/u', 'TR', {})
    burned = len(calls)

    fresh = KISDataProvider()
    fresh._token, fresh._base_url = 'tok', 'https://openapi.example'
    assert fresh._get('/u', 'TR', {}) == {}
    assert len(calls) == burned
