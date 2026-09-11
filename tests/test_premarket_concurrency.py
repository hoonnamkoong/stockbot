# -*- coding: utf-8 -*-
"""premarket_data.yml은 두 런이 동시에 돌면 안 된다.

2026-09-11 실측 — 태스커/수동 dispatch 런(08:43 KST)과 2시간 늦게 발화한 cron 런
(09:14 KST)이 둘 다 09:00~11:30 장중을 수집하고, 11:30에 같은 파일
(rt_intraday_20260911.csv.gz)을 2초 차이로 intraday-data에 push했다. 늦은 쪽이
add/add 충돌로 rebase에 실패해 사람을 불렀다.

반대 순서는 더 나쁘다. 적게 받은 런이 **나중에** 끝나면 그 시점 브랜치를 클론해
좋은 파일을 자기 파일로 덮어쓰고, 충돌이 없으니 push가 성공한다 — 조용한 결손이다.

동시 실행을 막으면 나중 런은 앞 런이 끝난 뒤(11:30 이후) 시작하고, 수집 창이
이미 닫혀 있어 웹소켓에 붙지 않는다(window_state == 'past').
"""
import os

import yaml

WF = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows',
                  'premarket_data.yml')


def _wf():
    with open(WF, encoding='utf-8') as f:
        return yaml.safe_load(f)


def test_워크플로_전체가_한_번에_한_런만_돈다():
    """잡 단위가 아니라 워크플로 단위여야 한다 — collect도 db-data에 같은 파일을 쓴다."""
    c = _wf().get('concurrency')
    assert c, 'concurrency가 없다 — 늦은 cron 런과 dispatch 런이 겹친다'
    assert c.get('group'), 'group이 없으면 직렬화되지 않는다'


def test_진행_중인_런을_취소하지_않는다():
    """취소하면 2.5시간째 수집 중인 런이 커밋 직전에 죽는다 — 그날 장중이 통째로 사라진다."""
    assert _wf()['concurrency'].get('cancel-in-progress') is False
