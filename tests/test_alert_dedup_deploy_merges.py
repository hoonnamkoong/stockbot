# -*- coding: utf-8 -*-
"""쿨다운 기록을 db-data에 올리는 경로는 전부 **병합**이어야 한다.

writer가 셋이다(trading.yml·scraper.yml·us_trading.yml). 하나라도 `cp`로
통째로 밀면 그 사이 다른 워크플로가 적은 억제 기록이 사라지고, 억제가 무력화돼
같은 장애가 2분마다 나간다. 2026-09-02에 정확히 그렇게 나갔다.
"""
import os
import re

import pytest

yaml = pytest.importorskip('yaml')

WF_DIR = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows')
MERGE_SCRIPT = 'scripts/merge_alert_dedup.py'
FILE = 'alert_dedup.json'


def _run_blocks(name):
    with open(os.path.join(WF_DIR, name), encoding='utf-8') as f:
        wf = yaml.safe_load(f)
    return [s.get('run', '') for job in wf['jobs'].values()
            for s in job.get('steps', []) if s.get('run')]


def _workflows():
    return sorted(n for n in os.listdir(WF_DIR) if n.endswith('.yml'))


def test_어느_워크플로도_쿨다운_기록을_통째로_밀지_않는다():
    offenders = []
    for name in _workflows():
        for run in _run_blocks(name):
            for line in run.splitlines():
                if FILE not in line or line.strip().startswith('#'):
                    continue
                if re.search(r'\bcp\b', line):
                    offenders.append(f'{name}: {line.strip()}')
    assert not offenders, (
        '쿨다운 기록을 cp로 덮어쓰는 자리가 있다 — 병합으로 바꿀 것:\n'
        + '\n'.join(offenders))


def test_쿨다운을_배포하는_워크플로는_병합_스크립트를_부른다():
    """이 파일을 언급하면서 병합을 안 부르면, 배포에서 빠졌거나 cp로 돌아간 것이다."""
    for name in _workflows():
        blocks = '\n'.join(_run_blocks(name))
        mentions = FILE in blocks
        # 제외 목록에만 등장하는 워크플로도 있다(그건 배포하지 않는다는 뜻).
        if mentions and MERGE_SCRIPT not in blocks:
            pytest.fail(
                f'{name}이 {FILE}을 다루면서 {MERGE_SCRIPT}를 부르지 않는다')


def test_병합_스크립트가_실재한다():
    path = os.path.join(os.path.dirname(__file__), '..', MERGE_SCRIPT)
    assert os.path.exists(path), f'{MERGE_SCRIPT}이 없다 — 배포가 조용히 깨진다'
