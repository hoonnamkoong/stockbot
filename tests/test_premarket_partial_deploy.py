# -*- coding: utf-8 -*-
"""수집이 실패해도 그때까지 모은 것은 배포한다.

GitHub은 앞 스텝이 실패하면 뒤 스텝을 건너뛴다. 그래서 프리마켓에서는 **잘린
자리 뒤의 배포가 통째로 사라졌다** — 오늘만 세 번째로 나온 같은 모양이다
(eod_data 분봉, trading 배포 충돌, 그리고 여기).

collect 잡: `NXT 프리마켓 체결 적재`가 마지막 데이터 스텝이다. 거기서 죽으면
그 앞에서 이미 만든 미국 지수·유니버스·뉴스·투자자 수급이 **전부** db-data에
못 올라간다. 커밋 스텝 주석은 "게이트를 걸지 않는다 — 한국 휴장일에도 미국
지수는 쌓여야 한다"라고 의도를 적어 뒀는데, 앞 스텝 실패에는 그 의도가 지켜지지
않았다.

intraday 잡: 2.5시간짜리 세션 중 한 번의 웹소켓 절단이 그날 rt_intraday를 통째로
날렸다(2026-09-03). 재접속을 넣었지만, 그래도 끝내 실패하는 날은 남는다.

분봉·체결 데이터는 **당일치만** 조회된다 — 부분이라도 남기는 것이 0보다 낫다.
"""
import os

import yaml

WF = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows',
                  'premarket_data.yml')


def _commit_steps():
    with open(WF, encoding='utf-8') as f:
        wf = yaml.safe_load(f)
    for job_name, job in wf['jobs'].items():
        for step in job['steps']:
            if (step.get('name') or '').startswith('커밋'):
                yield job_name, step


def test_커밋_스텝이_앞_스텝_실패에도_돈다():
    found = 0
    for job_name, step in _commit_steps():
        found += 1
        cond = step.get('if') or ''
        assert 'always()' in cond, (
            f'{job_name}/{step["name"]}: 조건이 `{cond or "(없음)"}` — 앞 스텝이 '
            '실패하면 건너뛴다. 그때까지 모은 데이터가 통째로 사라진다')
    assert found == 2, f'커밋 스텝을 2개 기대했는데 {found}개다'
