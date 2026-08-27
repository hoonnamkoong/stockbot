"""premarket_data.yml의 db-data push는 충돌하면 rebase 후 재시도해야 한다.

2026-08-27 확인: 이 워크플로의 최근 스케줄 런이 **전부** 실패였고, 원인은 매번
`! [rejected] db-data -> db-data (non-fast-forward)`였다. 수집은 다 해 놓고
마지막 push만 죽으니 us_daily.csv·프리마켓 CSV가 매일 통째로 버려졌다.

이 워크플로는 03:22 UTC(12:22 KST) — 장 한복판에 돈다. 그 시간대 db-data는
trading.yml이 2분마다 밀고 있어 충돌이 예외가 아니라 정상이다. trading.yml과
scraper.yml은 이미 rebase 재시도 루프를 갖고 있는데 여기만 없었다.
"""
import os

import yaml

WF = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows',
                  'premarket_data.yml')


def _db_data_push_steps():
    with open(WF, encoding='utf-8') as f:
        wf = yaml.safe_load(f)
    out = []
    for job_name, job in wf['jobs'].items():
        for step in job.get('steps', []):
            script = step.get('run') or ''
            if 'push origin db-data' in script:
                out.append((job_name, step.get('name', '?'), script))
    return out


def test_every_db_data_push_retries_after_rebase():
    steps = _db_data_push_steps()
    assert steps, 'db-data로 push하는 스텝을 못 찾았다 — 탐지 로직이 깨졌다'
    for job, name, script in steps:
        assert 'rebase' in script, (
            f'{job}/{name}: push 충돌 시 재시도가 없다 — 장중이라 충돌이 정상인 워크플로다')
        assert 'unshallow' in script, (
            f'{job}/{name}: shallow clone 상태로는 rebase가 안 된다')
