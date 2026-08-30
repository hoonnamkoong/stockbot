# -*- coding: utf-8 -*-
"""GitHub Actions 워크플로를 깨우는 최소 도구.

**표준 라이브러리만 쓴다.** 이 함수들을 부르는 스텝(trading.yml의 라우팅 뒤)은
pip install 앞에 있다 — 태스커 창의 절반 이상이 어느 장도 아니라 그 트리거가
checkout만 하고 끝나야 하기 때문이다.

`scripts/trade_loop.py`의 `dispatch_scraper`와 모양이 겹치지만 그쪽은 이미 설치가
끝난 매매 프로세스 안에서 돌아 requests를 쓴다. 여기서 그걸 import하면 pandas까지
딸려온다.

GITHUB_TOKEN으로도 된다: workflow_dispatch와 repository_dispatch는 GitHub이 재귀
방지 규칙에서 명시적으로 예외 처리한 두 이벤트다. 다만 부르는 워크플로에
`permissions: actions: write`가 있어야 한다.
"""
import json
import os
from urllib import error, request

_BASE = 'https://api.github.com/repos/{repo}/actions/workflows/{wf}'


def token() -> str | None:
    return os.environ.get('GH_PAT') or os.environ.get('GITHUB_TOKEN')


def repo() -> str:
    return os.environ.get('GITHUB_REPOSITORY') or 'hoonnamkoong/stockbot'


def _headers(tok: str) -> dict:
    return {'Authorization': f'token {tok}',
            'Accept': 'application/vnd.github.v3+json'}


def _get_json(url: str, tok: str) -> dict:
    req = request.Request(url, headers=_headers(tok))
    with request.urlopen(req, timeout=15) as res:
        return json.loads(res.read().decode())


def is_running(wf: str, log=print) -> bool | None:
    """실행 중(또는 대기 중)인가. 조회 자체가 실패하면 None."""
    tok = token()
    if not tok:
        return None
    base = _BASE.format(repo=repo(), wf=wf) + '/runs'
    try:
        for status in ('in_progress', 'queued'):
            if _get_json(f'{base}?status={status}&per_page=1', tok).get('total_count', 0) > 0:
                return True
        return False
    except (error.URLError, OSError, ValueError) as e:
        log(f'[Dispatch] {wf} 실행 여부 조회 실패: {e}')
        return None


def list_run_times(wf: str, per_page: int = 100, log=print) -> list[str] | None:
    """최근 런의 created_at(ISO, Z). 조회 실패는 None — 빈 목록과 구분한다."""
    tok = token()
    if not tok:
        return None
    url = _BASE.format(repo=repo(), wf=wf) + f'/runs?per_page={per_page}'
    try:
        return [r['created_at'] for r in _get_json(url, tok).get('workflow_runs', [])]
    except (error.URLError, OSError, ValueError, KeyError) as e:
        log(f'[Dispatch] {wf} 런 목록 조회 실패: {e}')
        return None


def ran_since(wf: str, since, log=print) -> bool | None:
    """since(tz 있는 datetime) 이후에 시작한 런이 있는가. 조회 실패는 None."""
    import datetime as _dt
    times = list_run_times(wf, log=log)
    if times is None:
        return None
    for raw in times:
        if _dt.datetime.fromisoformat(raw.replace('Z', '+00:00')) >= since:
            return True
    return False


def dispatch(wf: str, log=print) -> bool:
    tok = token()
    if not tok:
        log(f'[Dispatch] GH 토큰 없음 → {wf} dispatch 불가')
        return False
    req = request.Request(
        _BASE.format(repo=repo(), wf=wf) + '/dispatches',
        data=json.dumps({'ref': os.environ.get('GITHUB_REF_NAME') or 'main'}).encode(),
        headers={**_headers(tok), 'Content-Type': 'application/json'},
        method='POST')
    try:
        with request.urlopen(req, timeout=15):
            pass
    except (error.URLError, OSError) as e:
        log(f'[Dispatch] {wf} dispatch 실패: {e}')
        return False
    log(f'[Dispatch] {wf} dispatch 완료')
    return True
