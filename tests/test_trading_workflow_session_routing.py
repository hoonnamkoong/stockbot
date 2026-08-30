# -*- coding: utf-8 -*-
"""태스커 트리거 하나를 두 시장으로 가르는 워크플로 배선.

태스커 창이 09:00~15:30에서 **09:00~06:00 KST**로 넓어졌다. 미국 장중 루프를
GitHub 네이티브 cron으로 돌리던 방식이 2026-08-27부터 통째로 죽었기 때문이다
(발화 18 → 1 → 0건/일 — 목·금 세션 거래 0건).

**이 테스트가 지키는 것.** trade_loop.py에는 장중 시간 게이트가 없다(휴장일만
본다). 태스커가 09:00~15:30에만 불러줬으니 필요가 없었다. 창이 넓어진 지금
워크플로의 `if:`가 유일한 방벽이다 — 이게 빠지면 **밤새 실전 매매 루프가 돈다**:
KIS 토큰 갱신, 국면 갱신, 스크래퍼 dispatch, 주문 시도까지.
"""
import os

import yaml

WF_DIR = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows')


def _load(name):
    with open(os.path.join(WF_DIR, name), encoding='utf-8') as f:
        return yaml.safe_load(f)


def _steps(wf):
    return next(iter(wf['jobs'].values()))['steps']


def _index_of(steps, run_contains):
    for i, s in enumerate(steps):
        if run_contains in (s.get('run') or ''):
            return i
    raise AssertionError(f'`{run_contains}` 실행 스텝이 없다')


# ── 라우팅 ──────────────────────────────────────────────────────────
def test_라우팅이_설치보다_앞선다():
    """장 밖 트리거(하루 200건 남짓)가 pip install을 물면 안 된다."""
    steps = _steps(_load('trading.yml'))
    assert _index_of(steps, 'session_router.py') < _index_of(steps, 'pip install')


def test_라우팅_스텝에_id가_있다():
    steps = _steps(_load('trading.yml'))
    step = steps[_index_of(steps, 'session_router.py')]
    assert step.get('id') == 'route'
    assert 'GITHUB_OUTPUT' in step['run'], 'kr/us/eod를 스텝 출력으로 내보내야 한다'


def test_라우팅_판정이_로그에도_남는다():
    """리다이렉트만 하면 'kr=false를 썼다'와 '아무것도 안 썼다'가 로그에서 똑같다.

    둘 다 하위 스텝이 전부 스킵된 런으로 보인다. 이 `if:`가 장 밖에서 실전 매매
    루프가 도는 걸 막는 유일한 방벽이므로 그 둘은 구분돼야 한다.
    """
    steps = _steps(_load('trading.yml'))
    run = steps[_index_of(steps, 'session_router.py')]['run']
    assert 'tee' in run, f'판정이 로그에 안 남는다: {run.strip()!r}'


# ── 국내 경로 ───────────────────────────────────────────────────────
KR_GUARDED = [
    'scripts/trade_loop.py',      # 실전 주문
    'scripts/token_manager.py',   # KIS 토큰 갱신
    'pip install',
    'db-data',                    # 원격 상태 fetch / 배포
]


def test_국내_스텝은_전부_kr_게이트_뒤에_있다():
    steps = _steps(_load('trading.yml'))
    for marker in KR_GUARDED:
        for i, s in enumerate(steps):
            if marker not in (s.get('run') or ''):
                continue
            cond = s.get('if') or ''
            assert "steps.route.outputs.kr == 'true'" in cond, (
                f"{i}번 스텝(`{marker}`)에 kr 게이트가 없다 — 밤새 돈다: {cond!r}")


# ── 미국 경로 ───────────────────────────────────────────────────────
def test_미국장이면_us_trading을_깨운다():
    wf = _load('trading.yml')
    steps = _steps(wf)
    step = steps[_index_of(steps, 'dispatch_us_trading.py')]
    assert "steps.route.outputs.us == 'true'" in (step.get('if') or '')
    # workflow_dispatch를 GITHUB_TOKEN으로 내려면 이 권한이 있어야 한다.
    perms = next(iter(wf['jobs'].values()))['permissions']
    assert perms.get('actions') == 'write'
    env = {**(next(iter(wf['jobs'].values())).get('env') or {}), **(step.get('env') or {})}
    assert 'GITHUB_TOKEN' in env or 'GH_PAT' in env, 'dispatch에 토큰이 안 넘어간다'


def test_us_trading_cron은_백업_간격이다():
    """주 경로는 태스커다. cron은 태스커가 죽었을 때를 위한 30분 백업으로만 남는다.

    `*/5`로 되돌리면 GitHub이 발화를 통째로 드롭하던 그 상태로 돌아간다.
    """
    wf = _load('us_trading.yml')
    crons = [c['cron'] for c in (wf.get('on') or wf.get(True))['schedule']]
    assert crons, 'cron 백업이 사라졌다'
    for expr in crons:
        minute = expr.split()[0]
        assert not minute.startswith('*/'), f'{expr!r} — 분 필드가 다시 촘촘해졌다'
        assert len(minute.split(',')) <= 2, f'{expr!r} — 시간당 3회 이상'


def test_마감_뒤에_eod_배치를_깨운다():
    """eod_data.yml cron이 2026-08-27부터 11~12시간 밀렸다. 그 배치는 심9-1·심11의
    다음 세션 감시목록을 만들어, 지연이 09:00 KST를 넘기면 두 심이 세션을 잃는다."""
    steps = _steps(_load('trading.yml'))
    step = steps[_index_of(steps, 'dispatch_eod_data.py')]
    assert "steps.route.outputs.eod == 'true'" in (step.get('if') or '')


def test_eod_배치에_동시실행_방지가_있다():
    """태스커(2분 간격)와 cron 백업이 겹치면 db-data push에서 서로 밟는다."""
    wf = _load('eod_data.yml')
    assert (wf.get('concurrency') or {}).get('group'), 'concurrency 그룹이 없다'


def test_토큰_발급이_직렬화된다():
    """refresh_token dispatch가 같은 초에 여러 번 온다. KIS는 분당 1회만 발급한다."""
    wf = _load('token_refresh.yml')
    assert (wf.get('concurrency') or {}).get('group'), 'concurrency 그룹이 없다'
    assert (wf.get('concurrency') or {}).get('cancel-in-progress') is False, (
        '발급 도중에 끊으면 발급됐는데 저장 안 된 상태가 남는다')


def test_개장_직후에_신선도_감사를_깨운다():
    """산출물 감사는 실패 알림이 못 잡는 ②③유형(미발화·산출물 결손)을 덮는다."""
    steps = _steps(_load('trading.yml'))
    step = steps[_index_of(steps, 'dispatch_data_audit.py')]
    assert "steps.route.outputs.audit == 'true'" in (step.get('if') or '')


def test_감사기는_cron에_기대지_않는다():
    """cron이 08-27부터 11~12시간씩 밀리거나 드롭됐다. 그걸 감시하는 감사기를
    그 위에 올릴 수는 없다."""
    wf = _load('data_audit.yml')
    triggers = wf.get('on') or wf.get(True)
    assert 'schedule' not in triggers, '감사기가 cron에 의존한다'
    assert 'workflow_dispatch' in triggers


# ── 미발화 감지기 ───────────────────────────────────────────────────
def test_감지기는_감시대상과_다른_워크플로에_있다():
    """장중 루프 안에 두면 루프가 안 돌 때 감지기도 안 돈다(2026-08-27의 교훈)."""
    watchlist = _steps(_load('us_eod_watchlist.yml'))
    _index_of(watchlist, 'check_us_loop_fired.py')       # 있어야 한다
    for name in ('us_trading.yml', 'trading.yml'):
        runs = ' '.join((s.get('run') or '') for s in _steps(_load(name)))
        assert 'check_us_loop_fired.py' not in runs, f'{name}에 감지기가 있다'


def test_감지기가_런_목록을_읽을_권한이_있다():
    """permissions를 명시하면 안 적은 스코프는 none이다 — 조회가 403이 되고
    감지기는 '판정 생략'으로 조용히 지나간다."""
    wf = _load('us_eod_watchlist.yml')
    perms = next(iter(wf['jobs'].values()))['permissions']
    assert perms.get('actions') in ('read', 'write')


def test_감지기가_워치리스트_수집보다_먼저_돈다():
    """수집은 최대 40분이다. 그 뒤에 두면 알림이 40분 늦는다."""
    steps = _steps(_load('us_eod_watchlist.yml'))
    assert _index_of(steps, 'check_us_loop_fired.py') < _index_of(steps, 'run_eod_sim_us.py')
