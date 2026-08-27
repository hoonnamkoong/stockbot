"""eod_data.yml이 심 실행 전에 KIS 휴장일 달력을 러너로 내려받는지.

kr_calendar.watchlist_target_date()가 다음 개장일을 고를 때 이 파일을 읽는다.
없으면 주말만 거르는 근사로 떨어져, 연휴 직전 배치가 휴장일을 찍고 그 감시
목록은 아무도 못 읽는다(연휴 직후 첫 거래일 하루가 통째로 빈다).

달력은 db-data가 원본이고, 이 워크플로는 심 상태를 받으려고 이미 clone한다 —
같은 스텝에서 한 줄 더 받아오면 된다.
"""
import os

import yaml

from src import market_calendar

WF = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows',
                  'eod_data.yml')


def _eod_sim_step_script():
    with open(WF, encoding='utf-8') as f:
        wf = yaml.safe_load(f)
    for step in wf['jobs']['collect']['steps']:
        if 'run_eod_sims.py' in (step.get('run') or ''):
            return step['run']
    raise AssertionError('run_eod_sims.py를 도는 스텝이 eod_data.yml에 없다')


def test_calendar_is_restored_before_eod_sims_run():
    script = _eod_sim_step_script()
    calendar_file = os.path.basename(market_calendar.CALENDAR_PATH)
    assert calendar_file in script, (
        f'{calendar_file}을 러너로 안 받아온다 — 다음 개장일 판정이 주말 근사로 떨어진다')
    assert script.index(calendar_file) < script.index('run_eod_sims.py'), (
        '달력 복원이 심 실행보다 뒤에 있다')
