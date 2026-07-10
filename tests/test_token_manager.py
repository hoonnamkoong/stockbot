import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import pytest
import requests

# token_manager는 win32에서 import 시 sys.stdout을 TextIOWrapper로 교체하는데,
# 그 wrapper가 GC될 때 pytest의 캡처 버퍼까지 닫아버린다. import 동안만 플랫폼을 가린다.
_platform = sys.platform
sys.platform = 'linux'
import token_manager as tm
sys.platform = _platform


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


VALID_TOKEN = {"access_token": "abc", "expires_at": "2099-01-01T00:00:00+09:00"}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(tm.time, "sleep", lambda *_: None)


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setenv("GH_PAT", "fake-pat")
    monkeypatch.setenv("KIS_APP_KEY", "key")
    monkeypatch.setenv("KIS_APP_SECRET", "secret")
    monkeypatch.delenv("FORCE_TOKEN_REFRESH", raising=False)


@pytest.fixture(autouse=True)
def no_local_cache(monkeypatch):
    monkeypatch.setattr(tm.os.path, "exists", lambda p: False)


def test_repo_read_retries_then_succeeds(monkeypatch):
    """DNS 오류로 두 번 실패해도 세 번째 시도에서 토큰을 읽어야 한다."""
    attempts = []

    def fake_get(url, **kwargs):
        attempts.append(url)
        if len(attempts) < 3:
            raise requests.ConnectionError("Temporary failure in name resolution")
        return FakeResponse(200, VALID_TOKEN)

    monkeypatch.setattr(tm.requests, "get", fake_get)

    assert tm.load_token_cache() == VALID_TOKEN
    assert len(attempts) == 3


def test_repo_read_network_failure_raises_unavailable(monkeypatch):
    """재시도를 모두 소진한 네트워크 오류는 '토큰 없음'이 아니라 '접근 불가'다."""
    monkeypatch.setattr(
        tm.requests, "get",
        lambda url, **kw: (_ for _ in ()).throw(requests.ConnectionError("dns")),
    )

    with pytest.raises(tm.TokenSourceUnavailable):
        tm.load_token_cache()


def test_manage_does_not_issue_token_when_repo_unreachable(monkeypatch):
    """저장소에 못 닿으면 멀쩡한 토큰이 살아있을 수 있으므로 재발급하지 않는다."""
    monkeypatch.setattr(
        tm.requests, "get",
        lambda url, **kw: (_ for _ in ()).throw(requests.ConnectionError("dns")),
    )

    def must_not_be_called():
        raise AssertionError("네트워크 불가 상태에서 토큰 재발급을 시도했다")

    monkeypatch.setattr(tm, "issue_new_token", must_not_be_called)

    assert tm.manage() is False


def test_manage_issues_token_when_repo_has_none(monkeypatch):
    """404(최초 발급)는 네트워크 장애가 아니므로 정상적으로 발급한다."""
    monkeypatch.setattr(tm.requests, "get", lambda url, **kw: FakeResponse(404))
    issued = []
    monkeypatch.setattr(tm, "issue_new_token", lambda: issued.append(1) or VALID_TOKEN)
    monkeypatch.setattr(tm, "save_token_cache", lambda t: None)

    assert tm.manage() is True
    assert issued == [1]


def test_issue_new_token_retries_on_timeout(monkeypatch):
    """KIS 커넥트 타임아웃은 일시적이므로 재시도해야 한다."""
    attempts = []

    def fake_post(url, **kwargs):
        attempts.append(url)
        if len(attempts) < 3:
            raise requests.ConnectTimeout("connect timeout=10")
        return FakeResponse(200, VALID_TOKEN)

    monkeypatch.setattr(tm.requests, "post", fake_post)

    assert tm.issue_new_token() == VALID_TOKEN
    assert len(attempts) == 3


def test_issue_new_token_does_not_retry_on_explicit_rejection(monkeypatch):
    """KIS가 응답으로 거부하면(EGW 코드 등) 재시도는 의미가 없다."""
    attempts = []

    def fake_post(url, **kwargs):
        attempts.append(url)
        return FakeResponse(200, {"error_code": "EGW00123", "error_description": "unauthorized"})

    monkeypatch.setattr(tm.requests, "post", fake_post)

    assert tm.issue_new_token() is None
    assert len(attempts) == 1
