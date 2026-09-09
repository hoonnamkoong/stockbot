# -*- coding: utf-8 -*-
"""워크플로가 부르는 스크립트가 `src`를 찾을 수 있어야 한다.

2026-09-08 밤 공용 모듈 재편(#101~#103)이 `scripts/token_manager.py`에
`from src.core import clock`을 넣었다. 그 스크립트를 부르는 스텝 중
token_refresh.yml만 PYTHONPATH가 없었고, 다음 날 07:00 토큰 선발급이
`ModuleNotFoundError: No module named 'src'`로 죽었다.

**같은 런의 실패 알림 스텝도 같은 에러로 죽었다.** notify_workflow_failure.py
역시 `from src.core import notify`를 쓰는데 거기에도 PYTHONPATH가 없었다.
그래서 텔레그램은 한 통도 안 나갔고, 매매가 자가치유(첫 trading 런이 대신
발급)해 버린 탓에 대시보드도 정상으로 보였다. 조용한 실패였다.

리팩터는 스크립트를 고치지 워크플로를 고치지 않는다 — 이 어긋남은 다음에도
같은 방식으로 생긴다. 그래서 사람의 기억이 아니라 여기서 막는다.

스크립트가 스스로 `sys.path`에 레포 루트를 넣는다면 PYTHONPATH는 필요 없다
(dispatch_data_audit.py, check_heartbeat.py가 그렇다). 그건 통과시킨다 —
요구하는 것은 "import가 성공한다"이지 "PYTHONPATH를 쓴다"가 아니다.
"""
import os
import re

import yaml

ROOT = os.path.join(os.path.dirname(__file__), '..')
WF_DIR = os.path.join(ROOT, '.github', 'workflows')

SCRIPT_CALL = re.compile(r'(?<![\w/])scripts/([A-Za-z0-9_]+)\.py')


def _workflows():
    for name in sorted(os.listdir(WF_DIR)):
        if not name.endswith(('.yml', '.yaml')):
            continue
        with open(os.path.join(WF_DIR, name), encoding='utf-8') as f:
            yield name, yaml.safe_load(f)


def _needs_pythonpath(script):
    """이 스크립트는 레포 루트가 sys.path에 있어야만 import가 되는가."""
    path = os.path.join(ROOT, 'scripts', script)
    if not os.path.isfile(path):
        return False
    with open(path, encoding='utf-8') as f:
        source = f.read()
    imports_src = re.search(r'^\s*(?:from\s+src[.\s]|import\s+src\b)', source, re.M)
    self_inserts = 'sys.path.insert' in source or 'sys.path.append' in source
    return bool(imports_src) and not self_inserts


def _command_lines(run):
    """줄 끝 `\\` 이어쓰기를 한 줄로 합쳐서 돌려준다."""
    joined = re.sub(r'\\\s*\n\s*', ' ', run)
    return [line for line in joined.splitlines() if line.strip()]


def test_src를_import하는_스크립트를_부르는_스텝은_경로를_준다():
    missing = []
    for name, wf in _workflows():
        for job_name, job in wf['jobs'].items():
            job_env = job.get('env') or {}
            for step in job['steps']:
                run = step.get('run')
                if not run:
                    continue
                env = {**job_env, **(step.get('env') or {})}
                for line in _command_lines(run):
                    scripts = [s + '.py' for s in SCRIPT_CALL.findall(line)]
                    if not any(_needs_pythonpath(s) for s in scripts):
                        continue
                    if 'PYTHONPATH' in env or 'PYTHONPATH=' in line:
                        continue
                    missing.append(
                        f'{name}/{job_name}: {line.strip()} '
                        f'— PYTHONPATH가 없어 `src`를 못 찾는다'
                    )
    assert not missing, '\n'.join(missing)
