# -*- coding: utf-8 -*-
"""감사기(data_audit.yml)가 태스커 말고 다른 발화 경로를 갖는지 본다.

감사기는 "나와야 할 게 나왔나"를 보는 마지막 그물인데, 발화가 태스커(폰) →
trading.yml 하나뿐이면 **폰이 죽을 때 그물도 같이 죽는다.** 그리고 미발화는
빨간 X를 남기지 않아 아무도 모른다. 이 레포는 2026-08-27 us_trading에서 이미
그 모양을 겪었다.
"""
import os

import pytest

yaml = pytest.importorskip('yaml')

WF_DIR = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows')


def _load(name):
    with open(os.path.join(WF_DIR, name), encoding='utf-8') as f:
        return yaml.safe_load(f)


def _steps(wf):
    return [s for job in wf['jobs'].values() for s in job.get('steps', [])]


def test_감사기는_태스커와_다른_발화_경로를_갖는다():
    backup = _load('data_audit_backup.yml')
    # yaml이 `on:`을 불리언 True로 파싱한다
    assert 'schedule' in backup[True], 'cron이 없으면 태스커와 같은 경로다'


def test_백업은_판정을_복제하지_않고_같은_스크립트를_부른다():
    """'오늘 이미 돌았나'가 두 곳에 생기면 둘이 갈라진다."""
    runs = ' '.join(s.get('run', '') for s in _steps(_load('data_audit_backup.yml')))
    assert 'scripts/dispatch_data_audit.py' in runs


def test_감사기_본체에는_cron을_붙이지_않는다():
    """붙이면 중복 감사로 같은 알림이 두 번 나가고, 건너뛰면 아무것도 안 한 런이
    초록으로 남아 dispatch_data_audit.py의 '오늘 이미 돌았나'를 속인다."""
    assert 'schedule' not in _load('data_audit.yml')[True], (
        '중복 알림 또는 스킵-미발화 혼동이 생긴다 — 발화는 '
        'data_audit_backup.yml로 뺀다')
