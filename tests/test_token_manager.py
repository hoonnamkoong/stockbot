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


# ── 동시 트리거(EGW00133) ────────────────────────────────────────────
# repository_dispatch(refresh_token)가 같은 초에 여러 번 들어온다: 2026-08-30
# 10:59:01Z에 2건(1성공 1실패), 08-23 11:13:34~45에 4건(1성공 3실패). KIS는 토큰
# 발급을 분당 1회로 제한하므로(EGW00133) 늦게 도착한 런은 반드시 거부된다.
#
# 발급은 실제로 성공했는데 런만 빨갛다 — 그 빨강이 진짜 장애와 섞인다.
# 형제 런이 **방금** 발급해 저장소에 넣어 뒀다면 이 런의 목적은 이미 달성된 것이다.
# '방금'을 요구하는 게 핵심이다: 오래된(그러나 아직 안 만료된) 토큰까지 성공으로
# 봐주면 진짜 발급 실패가 조용해진다.

def _cache_issued_minutes_ago(minutes):
    issued = tm.get_current_kst_time() - tm.timedelta(minutes=minutes)
    return {"access_token": "abc",
            "issued_at": issued.isoformat(),
            "expires_at": (issued + tm.timedelta(hours=24)).isoformat()}


def test_형제_런이_방금_발급했으면_성공으로_본다(tmp_path, monkeypatch):
    """같은 초에 도착한 형제 런의 기록은 **읽는 순서**로만 보인다.

    첫 읽기(발급 시도 전)에는 저장소가 비어 있고, 형제가 그 사이에 쓴다.
    그래서 발급 거부 뒤 **다시 읽어야** 보인다 — 발급 앞의 레이트 가드는
    이 경우를 잡지 못한다(잡을 수가 없다). 두 판정은 겹치지 않는다.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORCE_TOKEN_REFRESH", "true")

    reads = []

    def fake_load():
        reads.append(1)
        return None if len(reads) == 1 else _cache_issued_minutes_ago(0)

    monkeypatch.setattr(tm, "load_token_cache", fake_load)
    monkeypatch.setattr(tm, "issue_new_token", lambda: None)   # EGW00133

    assert tm.manage() is True
    assert len(reads) == 2, "발급 거부 뒤 저장소를 다시 읽지 않았다"


def test_오래된_토큰은_발급실패를_덮지_않는다(monkeypatch):
    """아직 안 만료됐어도 '방금 발급'이 아니면 진짜 실패다 — 조용해지면 안 된다."""
    monkeypatch.setenv("FORCE_TOKEN_REFRESH", "true")
    monkeypatch.setattr(tm, "load_token_cache", lambda: _cache_issued_minutes_ago(600))
    monkeypatch.setattr(tm, "issue_new_token", lambda: None)

    assert tm.manage() is False


def test_토큰이_아예_없으면_실패다(monkeypatch):
    monkeypatch.setenv("FORCE_TOKEN_REFRESH", "true")
    monkeypatch.setattr(tm, "load_token_cache", lambda: None)
    monkeypatch.setattr(tm, "issue_new_token", lambda: None)

    assert tm.manage() is False


def test_형제_런_경로에서도_로컬_캐시를_남긴다(tmp_path, monkeypatch):
    """발급이 거부돼도 성공으로 처리한다면, 뒤 스텝이 쓸 로컬 캐시는 있어야 한다.

    2026-09-01 22:06Z 런: 발급 거부 → 형제 런 판정으로 성공 → 그런데
    data/kis_token_cache.json이 없어 다음 스텝이 죽었다
    (`[MarketCalendar] 갱신 실패: KIS 토큰 캐시가 없다`).
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORCE_TOKEN_REFRESH", "true")
    cache = _cache_issued_minutes_ago(1)
    monkeypatch.setattr(tm, "load_token_cache", lambda: cache)
    monkeypatch.setattr(tm, "issue_new_token", lambda: None)   # EGW00133

    assert tm.manage() is True

    import json
    written = json.loads((tmp_path / "data" / "kis_token_cache.json").read_text(encoding="utf-8"))
    assert written["access_token"] == cache["access_token"]


# ── 강제 갱신 레이트 가드 ──────────────────────────────────────────
# force의 유일한 정당한 용도는 장 전 하루 1회 선발급이다. 트리거가 한 번
# 어긋나자(07시대 라우팅) 2분마다 발급됐다 — 2026-09-02 07:00~07:50 26회.
# 그때 발급과 트리거 버그 사이에 있던 유일한 방어가 다른 언어·다른 레이어의
# 라우팅 함수(Vercel TS)였다. 돈 경로의 방어는 돈 경로 옆에 둔다.

def test_강제갱신이어도_방금_발급했으면_다시_발급하지_않는다(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORCE_TOKEN_REFRESH", "true")
    cache = _cache_issued_minutes_ago(2)
    monkeypatch.setattr(tm, "load_token_cache", lambda: cache)

    called = []
    monkeypatch.setattr(tm, "issue_new_token", lambda: called.append(1))

    assert tm.manage() is True
    assert called == [], "간격 안인데 KIS에 발급을 요청했다"


def test_강제갱신은_간격이_지나면_발급한다(tmp_path, monkeypatch):
    """가드가 하루 한 번의 장 전 선발급까지 막으면 안 된다."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORCE_TOKEN_REFRESH", "true")
    old = _cache_issued_minutes_ago(tm.FORCE_ISSUE_MIN_INTERVAL_MIN + 1)
    monkeypatch.setattr(tm, "load_token_cache", lambda: old)

    called = []
    monkeypatch.setattr(tm, "issue_new_token",
                        lambda: called.append(1) or {"access_token": "new"})
    monkeypatch.setattr(tm, "save_token_cache", lambda t: None)

    with pytest.raises(SystemExit):   # force 성공은 sys.exit(0)로 끝난다
        tm.manage()
    assert called == [1]


def test_만료된_토큰은_간격과_무관하게_발급한다(tmp_path, monkeypatch):
    """가드는 **유효한** 토큰이 있을 때만 막는다 — 진짜 필요한 발급은 안 막는다."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORCE_TOKEN_REFRESH", "true")
    expired = _cache_issued_minutes_ago(2)
    expired["expires_at"] = "2000-01-01T00:00:00+09:00"   # 방금 발급됐지만 만료
    monkeypatch.setattr(tm, "load_token_cache", lambda: expired)

    called = []
    monkeypatch.setattr(tm, "issue_new_token",
                        lambda: called.append(1) or {"access_token": "new"})
    monkeypatch.setattr(tm, "save_token_cache", lambda t: None)

    with pytest.raises(SystemExit):
        tm.manage()
    assert called == [1]
