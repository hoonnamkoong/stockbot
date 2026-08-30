# -*- coding: utf-8 -*-
"""db-data 배포는 **전용 클론 안에서** rebase해야 한다.

premarket_data.yml은 main 체크아웃 워킹트리에서 그대로 배포했다:

    git fetch origin db-data --depth=1        # shallow graft
    git checkout -B db-data origin/db-data
    ...commit...
    push → rejected (trading.yml이 2분마다 db-data를 민다)
    git fetch --unshallow origin db-data
    git pull --rebase origin db-data          # ← Rebasing (4/1287)

grafted 커밋 위에 만든 브랜치를 unshallow한 뒤 rebase하면 git이 **1287개 커밋**을
재생하려 든다. 매번 2026년 초 커밋(9f64d57a8)에서 충돌하고 재시도 3회가 전부 같은
자리에서 죽는다. 2026-08-16 도입 이래 10런 중 9번 실패했고, premarket_daily.csv·
premarket_universe.csv·investor_flows.csv·nxt_*.csv가 db-data에 아예 없었다.

trading.yml은 같은 재시도 루프를 쓰는데 멀쩡하다 — `git clone --branch db-data`로
**db-data 이력만 든 별도 저장소**를 만들어 그 안에서 돌기 때문이다. 거기서는
재생할 커밋이 방금 만든 하나뿐이다.

2026-08-27의 PR #60이 재시도 루프만 옮겨 오고 이 격리를 안 가져와서 안 고쳐졌다.
"""
import os

import yaml

WF_DIR = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows')


def _runs():
    """(워크플로, 스텝 이름, run 문자열) 전부."""
    for name in sorted(os.listdir(WF_DIR)):
        if not name.endswith(('.yml', '.yaml')):
            continue
        with open(os.path.join(WF_DIR, name), encoding='utf-8') as f:
            wf = yaml.safe_load(f)
        for job in (wf.get('jobs') or {}).values():
            for step in job.get('steps') or []:
                if step.get('run'):
                    yield name, step.get('name', '(이름 없음)'), step['run']


def test_rebase는_전용_클론_안에서만_한다():
    for wf, step, run in _runs():
        if 'git pull --rebase origin db-data' not in run:
            continue
        assert 'git clone' in run and '--branch db-data' in run, (
            f'{wf} / {step}: db-data를 전용 클론 없이 rebase한다 — '
            '워킹트리 이력이 통째로 재생돼 옛 커밋에서 충돌한다')


def test_워킹트리를_db_data로_갈아타지_않는다():
    """`git checkout -B db-data`는 main 워킹트리의 브랜치를 바꾼다.

    start point가 없는 폴백(`|| git checkout -B db-data`)은 **현재 HEAD(=main)**에
    브랜치를 만들어, 데이터 커밋이 main 이력 위에 얹힌다.
    """
    for wf, step, run in _runs():
        assert 'checkout -B db-data' not in run, (
            f'{wf} / {step}: 워킹트리를 db-data로 갈아탄다')
