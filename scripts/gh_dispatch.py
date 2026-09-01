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


def list_runs(wf: str, per_page: int = 100, log=print) -> list[dict] | None:
    """최근 런의 (created_at, status, conclusion). 조회 실패는 None.

    `list_run_times`는 시작 시각만 준다. 그래서 그것만 보는 호출자는 **실패한
    런과 성공한 런을 구분하지 못한다** — 2026-09-01에 EOD 배치가 KIS 타임아웃으로
    죽었는데, "오늘 런이 있다"는 이유로 남은 창에서 재시도가 통째로 막혔다.
    이 레포가 반복해서 겪은 "실패와 성공이 밖에서 같은 모양"의 또 한 사례다.
    """
    tok = token()
    if not tok:
        return None
    url = _BASE.format(repo=repo(), wf=wf) + f'/runs?per_page={per_page}'
    try:
        return [{'created_at': r['created_at'], 'status': r.get('status'),
                 'conclusion': r.get('conclusion')}
                for r in _get_json(url, tok).get('workflow_runs', [])]
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


def should_skip(runs: list[dict], now, since, max_attempts: int = 6,
                cooldown_min: int = 25) -> tuple[bool, str]:
    """태스커가 2분마다 때리는 창에서 "지금 깨울까"를 정한다. (생략할까, 이유).

    `since` 이후에 시작한 런만 본다 — 그 앞의 런은 다른 창의 것이라 없는 것과 같다.

    2026-09-01 하루에 세 번 고쳐진 판정이라 한 곳에 모았다:
      - **성공한 런이 있을 때만** '이미 돌았다'로 본다. 시작 시각만 보던 시절,
        KIS 타임아웃으로 죽은 EOD 배치가 **자기 재시도를 스스로 막았다.**
      - 실패에는 간격을 둔다. 간격이 없으면 상한을 장애 초반 몇 분에 소진하고
        그 뒤 회복해도 다시 안 깨운다.
      - 상한에 닿으면 멈추고 사람을 부른다. 태스커가 2분마다 들어오므로 상한이
        없으면 지속 장애에서 수십 번 dispatch한다.
    **상한과 간격은 같이 있어야 의미가 있다.**

    `conclusion`이 success도 None도 아니면 시도로 센다(cancelled 포함) — EOD에서
    쓰던 판정을 그대로 옮긴 것이다.
    """
    import datetime as _dt

    def _started(r):
        return _dt.datetime.fromisoformat(r['created_at'].replace('Z', '+00:00'))

    window = [r for r in runs if _started(r) >= since]

    if any(r.get('conclusion') == 'success' for r in window):
        return True, '창 안에 성공한 런이 있다'
    if any(r.get('status') in ('queued', 'in_progress') for r in window):
        return True, '지금 돌고 있다'

    failed = [r for r in window if r.get('conclusion') not in (None, 'success')]
    if len(failed) >= max_attempts:
        # 조용히 멈추면 안 된다 — 산출물이 없는 채로 다음 세션에 들어간다.
        return True, f'{len(failed)}회 실패 — 상한({max_attempts}) 도달, 사람이 봐야 한다'
    if failed:
        waited = (now - max(_started(r) for r in failed)).total_seconds() / 60
        if waited < cooldown_min:
            return True, (f'직전 실패로부터 {waited:.0f}분 — '
                          f'{cooldown_min}분 간격을 둔다')
        return False, f'{len(failed)}회 실패, {waited:.0f}분 경과 — 재시도한다'
    return False, '창 안에 런이 없다'


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
