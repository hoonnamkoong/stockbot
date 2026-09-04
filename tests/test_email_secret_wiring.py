# -*- coding: utf-8 -*-
"""메일을 보내는 스크립트는 자기가 읽는 이름으로 시크릿을 받아야 한다.

2026-09-04 발견: weekly_report.yml은 `GMAIL_USER`/`GMAIL_PASSWORD`를 넘기는데
src/weekly_reporter.py는 `EMAIL_USER`/`EMAIL_PASS`를 읽는다. 게다가
`GMAIL_PASSWORD`라는 시크릿은 레포에 없다(실재하는 이름은 `GMAIL_APP_PASSWORD`) —
런 로그에서 빈 값으로 찍힌다.

즉 이 배선으로는 주간 리포트 메일이 나갈 수 없다. 그런데 코드는 시크릿이 없으면
"EMAIL_USER or EMAIL_PASS missing"을 출력하고 **정상 종료**한다. 워크플로는
초록색이다 — 알림 없는 실패의 전형이다.

이름 대조는 사람이 못 하는 종류의 검사다(파일 두 개를 나란히 놓고 봐야 한다).
"""
import os
import re

import yaml

ROOT = os.path.join(os.path.dirname(__file__), '..')
WF_DIR = os.path.join(ROOT, '.github', 'workflows')

# (워크플로, 실행 스크립트, 그 스크립트가 os.environ으로 읽는 이름들)
CASES = [
    ('weekly_report.yml', 'src/weekly_reporter.py', {'EMAIL_USER', 'EMAIL_PASS'}),
    ('monthly_archive.yml', 'scripts/archive_monthly_data.py',
     {'EMAIL_USER', 'EMAIL_PASS'}),
]


def _step_env(workflow: str, run_contains: str) -> dict:
    with open(os.path.join(WF_DIR, workflow), encoding='utf-8') as f:
        wf = yaml.safe_load(f)
    for job in wf['jobs'].values():
        for step in job.get('steps', []):
            if run_contains in (step.get('run') or ''):
                return {**(job.get('env') or {}), **(step.get('env') or {})}
    raise AssertionError(f'{workflow}에서 `{run_contains}` 실행 스텝을 못 찾았다')


def test_스크립트가_읽는_이름으로_시크릿이_전달된다():
    for workflow, script, expected in CASES:
        # 스크립트가 실제로 그 이름을 읽는지부터 확인한다 — 기대값이 낡으면 무의미하다.
        src = open(os.path.join(ROOT, script), encoding='utf-8').read()
        read = set(re.findall(r"environ(?:\.get)?\(\s*'([A-Z_]+)'", src))
        assert expected <= read, (
            f'{script}가 {sorted(expected - read)}를 읽지 않는다 — 기대값이 낡았다')

        env = _step_env(workflow, script)
        missing = expected - set(env)
        assert not missing, (
            f'{workflow}가 {sorted(missing)}를 안 넘긴다 — 메일이 한 통도 안 나간다')
        for key in expected:
            assert f'secrets.{key}' in env[key], (
                f'{workflow}의 {key}가 시크릿에서 오지 않는다: {env[key]!r}')
