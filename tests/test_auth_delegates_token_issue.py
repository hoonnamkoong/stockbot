"""auth.py는 토큰을 발급하지 않는다 — 발급자는 scripts/token_manager.py 하나다.

2026-06-05(스크래퍼 하루 7회)과 2026-09-04(프리마켓 매 런) 두 번의 토큰 폭주가
모두 이 파일의 자가발급 경로였다. token_manager에는 가드가 넷 있는데
(형제 발급 창 10분 / 강제 갱신 최소 간격 30분 / 저장소 미도달 시 발급 안 함 /
네트워크 재시도 3회) auth.py에는 하나도 없어서 **"네트워크가 5초 느린 것"과
"토큰이 만료된 것"이 같은 결과**를 냈다.

지금까지의 수정은 전부 호출부였다 — "이 워크플로에도 token_manager 스텝을 붙여라".
그 목록은 새 워크플로가 생길 때마다 길어진다. 여기서는 **자원**을 고정한다:
발급 경로가 코드에 하나뿐이게 만들고, 새 발급 지점이 생기면 CI가 막는다.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# token_manager는 win32에서 import 시 sys.stdout을 TextIOWrapper로 교체하는데,
# 그 wrapper가 GC될 때 pytest의 캡처 버퍼까지 닫아버린다(test_token_manager.py와
# 같은 이유). auth.py가 함수 안에서 지연 import하므로, 여기서 미리 캐시에 올려
# 테스트 도중에 그 교체가 일어나지 않게 한다.
_platform = sys.platform
sys.platform = 'linux'
import scripts.token_manager as tm  # noqa: E402
sys.platform = _platform

from src.trade import auth  # noqa: E402

REPO = os.path.join(os.path.dirname(__file__), '..')
KIS_TOKEN_URL_RE = re.compile(r'oauth2/tokenP')


@pytest.fixture(autouse=True)
def cache_miss(monkeypatch):
    """로컬 캐시도 없고 비공개 레포에도 못 닿는 상태 — 옛 자가발급이 돌던 조건."""
    monkeypatch.setattr(auth.os.path, 'exists', lambda p: False)
    for name in ('GH_PAT', 'GITHUB_PAT', 'GITHUB_TOKEN'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('KIS_APP_KEY', 'key')
    monkeypatch.setenv('KIS_APP_SECRET', 'secret')


def test_cache_miss_does_not_request_a_token_from_kis(monkeypatch):
    """캐시가 없어도 auth.py가 직접 KIS에 발급을 요청하면 안 된다."""
    posted = []
    monkeypatch.setattr(auth.requests, 'post',
                        lambda url, **kw: posted.append(url))
    monkeypatch.setattr(tm, 'ensure_valid_token', lambda **kw: None,
                        raising=False)

    auth.get_access_token()

    assert not posted, (
        f'auth.py가 KIS에 직접 발급을 요청했다: {posted} — '
        '가드 없는 두 번째 발급자가 살아 있다')


def test_cache_miss_returns_the_token_from_the_single_issuer(monkeypatch):
    """발급이 필요하면 유일 발급자에게 맡기고, 그 결과를 그대로 쓴다."""
    monkeypatch.setattr(
        tm, 'ensure_valid_token',
        lambda **kw: {'access_token': 'issued-by-token-manager'},
        raising=False)

    assert auth.get_access_token() == 'issued-by-token-manager'


def test_issuer_refusal_is_not_papered_over(monkeypatch):
    """발급자가 '지금 발급하면 안 된다'고 판단하면 auth도 발급하지 않는다.

    token_manager는 저장소에 못 닿을 때 일부러 발급을 거른다 — 살아 있는 토큰을
    무효화하고 발급 제한만 소모하기 때문이다. auth가 그 판단을 뒤집으면
    가드를 넷 만든 의미가 없다.
    """
    posted = []
    monkeypatch.setattr(auth.requests, 'post',
                        lambda url, **kw: posted.append(url))
    monkeypatch.setattr(tm, 'ensure_valid_token', lambda **kw: None,
                        raising=False)

    assert auth.get_access_token() is None
    assert not posted


def _production_files(*suffixes):
    """프로덕션 소스 파일 — 레거시 백업·스크래치·테스트·빌드 산출물은 뺀다."""
    skip = ('_legacy_backups', 'scratch', 'tests', 'node_modules', '.git',
            '.next', 'out', 'dist')
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if f.endswith(suffixes):
                yield os.path.join(root, f)


def _production_py_files():
    return _production_files('.py')


def test_only_the_single_issuer_calls_the_kis_token_endpoint():
    """KIS 발급 엔드포인트를 부르는 프로덕션 파일은 token_manager 하나여야 한다.

    파일 목록이 아니라 규칙으로 검사한다 — 다음에 KIS를 쓰는 코드가 생겨도 잡힌다.
    진단용 스크립트(scripts/test_kis*.py)는 사람이 손으로 부르는 도구라 제외한다.
    """
    allowed = {os.path.normpath('scripts/token_manager.py')}
    diagnostics = re.compile(r'scripts[\\/]test_kis')

    offenders = []
    for path in _production_py_files():
        rel = os.path.normpath(os.path.relpath(path, REPO))
        if rel in allowed or diagnostics.search(rel):
            continue
        with open(path, encoding='utf-8', errors='replace') as f:
            if KIS_TOKEN_URL_RE.search(f.read()):
                offenders.append(rel)

    assert not offenders, (
        f'{offenders}가 KIS 발급 엔드포인트를 직접 부른다 — '
        '발급자는 scripts/token_manager.py 하나여야 한다')


def test_no_typescript_route_issues_a_kis_token():
    """대시보드(Vercel) 쪽에도 발급 지점이 없어야 한다.

    src/middleware.ts의 matcher는 /trade·/research뿐이라 /api/debug/* 는
    **무인증 공개**다. 거기서 KIS 발급 엔드포인트를 부르면 GET 한 번마다 새 토큰이
    나가고, 그 발급은 stockbot-secret에 기록되지 않아 **이력에 흔적이 안 남는다**
    (silent-path-leaves-no-ledger). KIS는 분당 1회 발급 제한이 있어, 크롤러 한 대가
    장 중에 이 경로를 긁으면 진짜 필요한 발급이 막힐 수 있다.

    TS에서 토큰이 필요하면 src/lib/kis-api.ts처럼 비공개 레포를 **읽고**,
    무효하면 refresh_token을 dispatch한다 — 직접 발급하지 않는다.
    """
    offenders = []
    for path in _production_files('.ts', '.tsx'):
        with open(path, encoding='utf-8', errors='replace') as f:
            if KIS_TOKEN_URL_RE.search(f.read()):
                offenders.append(os.path.normpath(os.path.relpath(path, REPO)))

    assert not offenders, (
        f'{offenders}가 KIS 발급 엔드포인트를 직접 부른다 — '
        'TS는 비공개 레포를 읽고 refresh_token을 dispatch해야 한다')
