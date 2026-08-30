# -*- coding: utf-8 -*-
"""국내 트리거(trading.yml)에서 미국 장중 루프(us_trading.yml)를 깨운다.

    python3 scripts/dispatch_us_trading.py

**왜 requests가 아니라 urllib인가.** 이 스텝은 pip install 앞에서 돈다
(scripts/session_router.py와 같은 이유 — 미국 세션 동안 2분마다 도는 경로에
설치 20초를 붙일 이유가 없다). trade_loop.py의 dispatch_scraper와 모양이
비슷하지만 그쪽은 이미 설치가 끝난 매매 프로세스 안에서 돌아 requests를 쓴다.

**왜 GITHUB_TOKEN으로 되는가.** workflow_dispatch와 repository_dispatch는
GitHub이 재귀 방지 규칙에서 명시적으로 예외 처리한 두 이벤트다. 다만 부르는
워크플로에 `permissions: actions: write`가 있어야 한다.
"""
import json
import os
from urllib import error, request

_WORKFLOW = 'us_trading.yml'
_API = 'https://api.github.com/repos/{repo}/actions/workflows/' + _WORKFLOW


def _token() -> str | None:
    return os.environ.get('GH_PAT') or os.environ.get('GITHUB_TOKEN')


def _repo() -> str:
    return os.environ.get('GITHUB_REPOSITORY') or 'hoonnamkoong/stockbot'


def _get_json(url: str, token: str) -> dict:
    req = request.Request(url, headers={
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'})
    with request.urlopen(req, timeout=10) as res:
        return json.loads(res.read().decode())


def is_running(token: str, log=print) -> bool | None:
    """실행 중(또는 대기 중)인가. 조회 자체가 실패하면 None."""
    base = _API.format(repo=_repo()) + '/runs'
    try:
        for status in ('in_progress', 'queued'):
            if _get_json(f'{base}?status={status}&per_page=1', token).get('total_count', 0) > 0:
                return True
        return False
    except (error.URLError, OSError, ValueError) as e:
        log(f'[US-Dispatch] 실행 여부 조회 실패: {e}')
        return None


def dispatch_us_trading(log=print) -> str:
    """'dispatched' | 'skipped' | 'failed' | 'no-token'."""
    token = _token()
    if not token:
        log('[US-Dispatch] GH 토큰 없음 → dispatch 불가')
        return 'no-token'

    running = is_running(token, log)
    if running is not False:
        # True(실행 중)든 None(조회 실패)든 부르지 않는다. 2분 뒤 다음 트리거가
        # 다시 시도하고, 대기열이 취소돼 사이클이 통째로 사라지는 쪽이 더 비싸다.
        log('[US-Dispatch] 이미 실행 중이거나 확인 불가 — dispatch 생략')
        return 'skipped'

    req = request.Request(
        _API.format(repo=_repo()) + '/dispatches',
        data=json.dumps({'ref': os.environ.get('GITHUB_REF_NAME') or 'main'}).encode(),
        headers={'Authorization': f'token {token}',
                 'Accept': 'application/vnd.github.v3+json',
                 'Content-Type': 'application/json'},
        method='POST')
    try:
        with request.urlopen(req, timeout=10):
            pass
    except (error.URLError, OSError) as e:
        log(f'[US-Dispatch] dispatch 실패: {e}')
        return 'failed'
    log('[US-Dispatch] dispatch 완료')
    return 'dispatched'


if __name__ == '__main__':
    # dispatch 실패로 국내 워크플로를 빨갛게 만들지 않는다 — 미국 심은 페이퍼이고
    # 이 워크플로의 본업은 실전 매매다. 침묵이 길어지는 건 세션 밖 감지기가 잡는다
    # (scripts/check_us_loop_fired.py).
    dispatch_us_trading()
