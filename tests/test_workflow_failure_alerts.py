# -*- coding: utf-8 -*-
"""모든 워크플로 잡은 실패하면 사람을 부른다.

2026-08-30 실측이 이 테스트의 이유다. `if: failure()` 알림이 있는 워크플로는
trading·scraper·monthly_report 셋뿐이었고, **그 셋의 최근 30런 실패는 0**이었다.
알림이 없는 나머지에만 실패가 쌓여 있었다:

    premarket_data      9 / 10   (2주간 방치, db-data에 산출물이 하나도 없었음)
    token_refresh      10 / 30   (전부 EGW00133)
    us_eod_watchlist    2 /  8   (나스닥 스크리너 소프트 차단 — 조사 때 처음 발견)
    eod_data            1

상관이 아니라 인과다. 알림이 오는 워크플로는 그날 고쳐지고, 안 오는 건 몇 주
쌓인다. "매일 체크"는 대시보드(산출물)를 보지 파이프라인(생산자)을 보지 않는다.

tests.yml만 예외다 — CI 실패는 PR에서 이미 보이고, 거기가 사람이 보고 있는 곳이다.
"""
import os

import yaml

WF_DIR = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows')
EXEMPT = {'tests.yml', 'pr_checklist.yml'}   # CI 실패는 PR에서 보인다 —
                                            # 거기가 사람이 보고 있는 곳이다


def _workflows():
    for name in sorted(os.listdir(WF_DIR)):
        if not name.endswith(('.yml', '.yaml')):
            continue
        with open(os.path.join(WF_DIR, name), encoding='utf-8') as f:
            yield name, yaml.safe_load(f)


def test_모든_잡이_실패하면_사람을_부른다():
    for name, wf in _workflows():
        if name in EXEMPT:
            continue
        for job_name, job in wf['jobs'].items():
            # `failure()`는 잡 타임아웃(cancelled)에 안 걸린다. eod_data는
            # 그 구멍으로 사흘을 침묵했고 `always() && job.status != 'success'`로
            # 바꿨다. 둘 다 "성공이 아니면 부른다"의 표현이라 함께 받는다.
            alerts = [s for s in job['steps']
                      if 'failure()' in (s.get('if') or '')
                      or "job.status != 'success'" in (s.get('if') or '')]
            assert alerts, f'{name}/{job_name}: 실패해도 아무도 안 부른다'
            for s in alerts:
                assert 'notify_workflow_failure.py' in (s.get('run') or ''), (
                    f'{name}/{job_name}: 억제 없는 알림이다 — 지속 실패에 '
                    '수백 통이 나가고 도배는 침묵과 같다')


def test_알림_스텝이_필요한_것을_다_받는다():
    for name, wf in _workflows():
        if name in EXEMPT:
            continue
        for job_name, job in wf['jobs'].items():
            for s in job['steps']:
                if 'notify_workflow_failure.py' not in (s.get('run') or ''):
                    continue
                env = {**(job.get('env') or {}), **(s.get('env') or {})}
                for key in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'):
                    assert key in env, f'{name}/{job_name}: {key} 없음 — 한 통도 안 나간다'
                assert env.get('WORKFLOW_FILE') == name, (
                    f'{name}/{job_name}: WORKFLOW_FILE이 {env.get("WORKFLOW_FILE")!r} '
                    '— 남의 런 이력을 보고 억제 판단을 한다')


def test_런_이력을_읽을_권한이_있다():
    """permissions를 명시하면 안 적은 스코프는 none이다. 조회가 막히면 억제가
    풀려(fail-loud) 지속 실패에 도배가 된다."""
    for name, wf in _workflows():
        if name in EXEMPT:
            continue
        for job_name, job in wf['jobs'].items():
            perms = job.get('permissions')
            if perms is None:
                continue        # 블록이 없으면 기본 토큰 권한을 따른다
            assert perms.get('actions') in ('read', 'write'), (
                f'{name}/{job_name}: actions 권한이 없어 런 이력을 못 읽는다')


def test_eod_알림이_취소된_런도_잡는다():
    """`if: failure()`는 타임아웃에 안 걸린다 — 타임아웃의 결론은 cancelled다.

    2026-09-01~09-03 eod_data의 전 런이 20분 타임아웃에 잘렸는데 텔레그램은
    한 통도 안 나갔다. 결국 알아챈 건 trade_loop의 eod_batch_stale이었다 —
    감시 대상과 다른 발화 경로에 둔 감지기가 유일한 방어였다.

    타임아웃이 있는 잡은 다른 워크플로에도 있다(2026-09-04 기준 9개). 여기서는
    실제로 잘린 eod_data만 고친다 — 나머지는 별건이다.
    """
    _, wf = next((n, w) for n, w in _workflows() if n == 'eod_data.yml')
    for job_name, job in wf['jobs'].items():
        conds = [s.get('if') or '' for s in job['steps']
                 if 'notify_workflow_failure.py' in (s.get('run') or '')]
        assert conds, f'eod_data/{job_name}: 실패 알림 스텝이 없다'
        for c in conds:
            assert 'always()' in c and "job.status != 'success'" in c, (
                f'eod_data/{job_name}: 알림 조건이 `{c}` — 잡 타임아웃에 안 걸린다. '
                '사흘간 침묵한 이유가 이것이다. cancelled()는 워크플로 취소를 보는 '
                '함수라 잡 타임아웃을 보장하지 못한다')
