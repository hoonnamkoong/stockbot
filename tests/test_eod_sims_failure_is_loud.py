"""EOD 심 실행이 실패하면 런이 빨개져야 한다.

`eod_data.yml`은 심 실행을 `python scripts/run_eod_sims.py || echo "…"`로 감싼다.
그 `|| echo`는 **의도된 것**이다 — 심이 실패해도 뒤의 CSV 배포는 돌아야 한다.
끊으면 2026-08-05 사고(심9-1이 매일 매수하고도 db-data에 한 번도 반영 안 됨)를
재현한다([[cut-step-kills-the-deploy-behind-it]]).

문제는 `|| echo`가 **종료코드를 삼켜 런이 초록으로 끝난다**는 것이다.
`run_eod_sims.main()`은 `return 0 if (r1 == 0 or r2 == 0) else 1`이라 두 심이 다
실패하면 1을 낸다. 2026-09-10에 실제로 그랬다 — 유니버스 0건으로 둘 다 실패해
exit 1이었는데 런은 success였고, 그 결과 **09-11 하루 종일 심11이 무장해제되고
심9-1이 미실행**됐다.

신선도 감사도 못 잡는다: 감시 항목이 `max_age_sessions: 1`이라 **1세션 지연을
허용**한다. 09-10에 감시목록이 안 만들어져 09-09 것이 남아도 그 창 안이다.

해법은 이 파일이 **이미 쓰고 있는 패턴**이다 — 배포 스텝의 `csv_ok`가
"상태는 올리고, 실패는 맨 끝에서 낸다"를 한다. 차이는 심 실행과 배포가 **서로 다른
스텝**이라는 것뿐이라, 셸 변수 대신 스텝 출력으로 넘긴다.

런이 빨개지면 기존 실패 알림(`scripts/notify_workflow_failure.py`)이 그대로 사람을
부른다 — 새 알림 배선이 필요 없다.
"""
import os
import re

WF = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows', 'eod_data.yml')


def _wf():
    with open(WF, encoding='utf-8') as f:
        return f.read()


def test_the_sim_step_still_lets_the_deploy_run():
    """회귀 방지 — 실패를 시끄럽게 만들면서 배포를 끊으면 2026-08-05로 되돌아간다."""
    wf = _wf()
    m = re.search(r'python scripts/run_eod_sims\.py(.*)', wf)
    assert m, 'run_eod_sims.py 호출을 못 찾았다'
    assert '||' in m.group(1), (
        '심 실행 실패가 스텝을 즉시 끊는다 — 뒤의 CSV 배포가 죽는다')


def test_a_sim_failure_is_recorded_for_the_end_of_the_run():
    """실패 사실이 스텝 밖으로 나가야 맨 끝에서 런을 빨갛게 만들 수 있다."""
    wf = _wf()
    m = re.search(r'python scripts/run_eod_sims\.py(.*)', wf)
    assert 'GITHUB_OUTPUT' in m.group(1) or 'GITHUB_ENV' in m.group(1), (
        '심 실행 실패가 스텝 출력으로 남지 않는다 — 삼켜져서 런이 초록으로 끝난다 '
        '(2026-09-10 실측: exit 1인데 success)')


def test_the_run_fails_at_the_end_when_the_sims_failed():
    """맨 끝에서 실제로 exit 1을 내야 기존 실패 알림이 사람을 부른다."""
    wf = _wf()
    assert re.search(r'sims_ok.*==.*0|sims_ok.*!=.*1|sims_ok.*=.*.0.', wf), (
        '심 실패 플래그를 읽어 런을 실패시키는 곳이 없다')
    # 배포보다 뒤에 있어야 한다 — 앞에서 끊으면 배포가 죽는다
    deploy_at = wf.index('Deploy CSV to db-data')
    fail_at = max(m.start() for m in re.finditer(r'sims_ok', wf))
    assert fail_at > deploy_at, (
        '심 실패 판정이 배포 스텝보다 앞에 있다 — 배포를 끊으면 안 된다')
