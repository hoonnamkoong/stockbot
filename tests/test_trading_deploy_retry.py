# -*- coding: utf-8 -*-
"""trading.yml의 배포 재시도는 3분 잡 예산 안에 들어가야 한다.

`Deploy state (db-data)`는 정상 8초인데, push가 충돌하면 `git fetch --unshallow`로
db-data 이력을 통째로 내려받는다. 그 브랜치는 2026-09-04 기준 **6707커밋**이고,
us_trading.yml은 같은 경로를 **142초**로 실측해 두었다(2026-08-26).

trading의 예산은 3분(180초)이고 정상 런이 이미 105초를 쓴다. 즉 충돌하면
**반드시** 잘린다 — 2026-09-04 실측 114런 중 6런(5.3%)이 그렇게 죽었고,
잘린 자리가 `Run trade loop` 또는 이 배포 스텝이었다:

    02:13:37 Deploy state 시작
    02:13:44 [Deploy] push 충돌 — rebase 후 재시도 (1/3)
    02:15:22 ##[error]The operation was canceled.   ← 98초 침묵

돈 경로인데 알림도 안 나간다(`if: failure()`는 cancelled를 못 잡는다).

**예산을 늘려서 풀 수 없다.** 이 타임아웃은 원장 락 리스(_LOCK_LEASE_MIN=4분)보다
짧아야 한다 — 리스가 만료될 때까지 살아 있는 런이 있으면 다른 런이 락을 회수해
같은 주문을 낸다. 그래서 충돌 경로 자체가 싸져야 한다.

rebase가 필요 없는 작업이기도 하다. 이 스텝이 하는 일은 "남의 최신 상태 위에 내
파일을 얹는다"이고, 그건 **다시 clone(depth 1, 약 6초)** 하면 그만이다.
"""
import os
import re

import yaml

WF = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows',
                  'trading.yml')


def _deploy_step_run() -> str:
    with open(WF, encoding='utf-8') as f:
        wf = yaml.safe_load(f)
    for step in wf['jobs']['trade']['steps']:
        if (step.get('name') or '').startswith('Deploy state'):
            return step['run']
    raise AssertionError('trading.yml에서 Deploy state 스텝을 못 찾았다')


def _commands(run: str) -> str:
    """주석은 뺀다 — 왜 안 쓰는지 적어 둔 문장까지 잡으면 안 된다."""
    return '\n'.join(ln for ln in run.splitlines()
                     if not ln.lstrip().startswith('#'))


def test_배포_재시도가_이력_전체를_내려받지_않는다():
    run = _commands(_deploy_step_run())
    assert '--unshallow' not in run, (
        'db-data는 6707커밋이고 unshallow는 실측 142초다 — 3분 예산 안에 '
        '들어갈 수 없다. 충돌 시 다시 clone(depth 1)하는 쪽이 싸고 결과가 같다')
    assert '--deepen' not in run, (
        'deepen도 이력 길이에 비례한다 — 재시도는 depth 1 clone으로 한다')


def test_충돌_재시도가_새로_clone한다():
    """남의 커밋 위에 얹는 방법이 rebase가 아니라 '최신을 다시 받아서 얹기'다."""
    run = _deploy_step_run()
    clones = re.findall(r'git clone .*--depth 1', run)
    assert clones, 'depth 1 clone이 없다'
    # 재시도 루프 안에서 clone이 다시 일어나야 한다.
    loop = run[run.index('for i in 1 2 3'):] if 'for i in 1 2 3' in run else ''
    assert loop, '재시도 루프가 없다'
    assert 'attempt' in loop or 'clone' in loop, (
        '재시도가 clone을 다시 하지 않는다 — 낡은 워킹카피 위에서 rebase하게 된다')
