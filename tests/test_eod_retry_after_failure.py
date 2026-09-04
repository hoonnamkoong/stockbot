"""실패한 EOD 배치는 다시 깨워야 한다 — 자기 재시도를 스스로 막으면 안 된다.

2026-09-01 16:00, EOD 배치가 KIS 연결 타임아웃(재시도 3회 모두 실패)으로 죽었다.
그런데 판정이 `already_ran(created_ats)` — **시작 시각만** 봤다. 그래서 "오늘 런이
있다"는 이유로 남은 창(16:00~17:00)에서 재시도가 통째로 막혔다.

이 배치는 심9-1(돈치안)·심11(미너비니)의 **다음 세션 감시목록**을 만든다.
안 만들어지면 두 심이 다음 날을 통째로 잃는다. 실제로 그날 감시목록은
`date: 20260901`에 머물렀다 — 09-02에 쓸 수 없는 값이다.

이 레포가 반복해서 겪은 형태다: **실패와 성공이 밖에서 같은 모양이다.**
(스킵과 미발화가 같은 모양이던 session_router, 초록인데 안 돈 cron …)

무한 재시도는 반대편 사고다. 태스커가 2분마다 들어오므로 상한이 없으면 지속
장애에서 30번 깨운다.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.dispatch_eod_data import (  # noqa: E402
    _MAX_ATTEMPTS, _RETRY_COOLDOWN_MIN, should_skip)

_KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime(2026, 9, 1, 16, 30, tzinfo=_KST)


def _run(hhmm, conclusion='success', status='completed'):
    h, m = hhmm
    ts = dt.datetime(2026, 9, 1, h, m, tzinfo=_KST).astimezone(dt.timezone.utc)
    return {'created_at': ts.isoformat().replace('+00:00', 'Z'),
            'status': status, 'conclusion': conclusion}


def test_success_today_means_skip():
    skip, why = should_skip([_run((16, 0))], NOW)
    assert skip and '성공' in why


def test_failure_today_means_retry():
    """이게 2026-09-01에 막혀 있던 경로다."""
    skip, why = should_skip([_run((16, 0), 'failure')], NOW)
    assert not skip, f'실패한 런이 재시도를 막는다: {why}'
    assert '재시도' in why


def test_in_progress_means_skip():
    """돌고 있는데 또 깨우면 db-data push에서 서로 밟는다."""
    skip, why = should_skip(
        [_run((16, 20), conclusion=None, status='in_progress')], NOW)
    assert skip and '돌고 있다' in why


def test_retry_is_bounded():
    """태스커가 2분마다 들어온다 — 상한이 없으면 지속 장애에서 수백 번 깨운다."""
    runs = [_run((16, 0), 'failure')] * _MAX_ATTEMPTS
    skip, why = should_skip(runs, NOW)
    assert skip and '상한' in why and '사람이 봐야' in why


def test_retries_are_spaced_out():
    """상한과 간격은 같이 있어야 한다.

    2026-09-01의 외부 장애는 몇 시간짜리였다. 간격이 없으면 상한 6회를 12분
    만에 소진하고, 그 뒤 KIS가 회복해도 다시 안 깨운다.
    """
    just_failed = dt.datetime(2026, 9, 1, 16, 20, tzinfo=_KST)
    skip, why = should_skip([_run((16, 10), 'failure')], just_failed)
    assert skip and '간격' in why, f'간격 없이 바로 재시도한다: {why}'


def test_retry_after_the_cooldown():
    later = dt.datetime(2026, 9, 1, 16, 10, tzinfo=_KST) + dt.timedelta(
        minutes=_RETRY_COOLDOWN_MIN + 1)
    skip, why = should_skip([_run((16, 10), 'failure')], later)
    assert not skip and '재시도' in why


def test_one_below_the_cap_still_retries():
    """상한 직전이어도, 간격만 지났으면 다시 깨운다."""
    runs = [_run((16, 0), 'failure')] * (_MAX_ATTEMPTS - 1)
    assert should_skip(runs, NOW)[0] is False


def test_runs_before_the_close_do_not_count():
    """장 마감 전 런은 종가를 담지 못한다 — 오늘 배치로 치면 안 된다."""
    skip, why = should_skip([_run((14, 0))], NOW)
    assert not skip and '없다' in why


def test_yesterdays_success_does_not_count():
    ts = dt.datetime(2026, 8, 31, 16, 0, tzinfo=_KST).astimezone(dt.timezone.utc)
    runs = [{'created_at': ts.isoformat().replace('+00:00', 'Z'),
             'status': 'completed', 'conclusion': 'success'}]
    assert should_skip(runs, NOW)[0] is False


def test_no_runs_today_dispatches():
    assert should_skip([], NOW)[0] is False


def test_cancelled_counts_as_a_failed_attempt():
    """취소도 산출물을 안 남긴다. 성공이 아닌 것은 전부 재시도 대상이다."""
    skip, _ = should_skip([_run((16, 0), 'cancelled')], NOW)
    assert skip is False


def test_window_is_wide_enough_to_outlast_an_outage():
    """창이 1시간이면 몇 시간짜리 외부 장애를 못 버틴다.

    2026-09-01이 그랬다 — 16:00 실패, 16:46 재시도도 실패, 17:00에 창이 닫혔다.
    그 하루를 놓치면 심9-1·심11이 다음 세션을 통째로 잃는다.
    """
    from src.session_gate import kr_eod_window
    naive = lambda h, m: dt.datetime(2026, 9, 1, h, m)
    assert kr_eod_window(naive(16, 0)) is True
    assert kr_eod_window(naive(20, 0)) is True, '저녁까지 재시도할 수 있어야 한다'
    assert kr_eod_window(naive(22, 59)) is True
    assert kr_eod_window(naive(23, 0)) is False
    assert kr_eod_window(naive(15, 59)) is False, '마감 전에는 종가가 없다'


def _eod_jobs() -> dict:
    import yaml
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        '..', '.github', 'workflows', 'eod_data.yml')
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)['jobs']


def test_eod_collect_job_timeout_fits_the_retry_interval():
    """매달린 런은 그날의 재시도를 통째로 막는다.

    2026-09-01: KIS 연결이 러너에서 타임아웃 나면서 EOD 런이 25분 넘게
    매달렸다. `should_skip`은 `in_progress`를 "지금 돌고 있다"로 보고 생략하므로,
    재시도 창을 23:00까지 넓혀도 **앞 런이 안 죽으면 소용이 없다.**
    이 워크플로만 타임아웃이 없었고 GitHub 기본값은 6시간이다.

    재시도 간격(25분)보다 짧아야 다음 트리거가 이어받는다. 이 부등식은
    **collect 잡에만** 건다 — 재시도로 되살릴 수 있는 산출물이 여기 있다.
    """
    job = _eod_jobs()['collect']
    t = job.get('timeout-minutes')
    assert t, 'collect 잡에 타임아웃이 없다 — 매달린 런이 재시도를 막는다'
    assert t < _RETRY_COOLDOWN_MIN, (
        f'타임아웃({t}분)이 재시도 간격({_RETRY_COOLDOWN_MIN}분)보다 길다 — '
        f'다음 트리거가 이어받지 못한다')


def test_minute_bars_lives_outside_the_collect_budget():
    """분봉 수집은 collect의 재시도 예산 안에 들어갈 수 없다.

    2026-08-31 마지막 성공 런 실측: 잡 전체 40분 15초 중 `Save minute bars`가
    **30분 13초**(211종목 × 앵커 13콜). 09-01에 20분 타임아웃을 걸 때 이 스텝을
    계산에서 뺐고("정상 수집은 3~5분"), 그날부터 09-03까지 전 런이 잘렸다.
    잘린 자리가 분봉이라 **그 뒤의 배포가 통째로 skipped** — 심9-1 상태와
    심11 감시목록이 사흘간 db-data에 안 올라갔다.

    분봉을 별도 잡에 두면 감시목록 배포가 분봉에 인질로 잡히지 않는다.
    """
    jobs = _eod_jobs()

    def _runs_minute_bars(job):
        return any('save_minute_bars.py' in (st.get('run') or '')
                   for st in job.get('steps') or [])

    assert not _runs_minute_bars(jobs['collect']), (
        'collect 잡이 분봉을 수집한다 — 실측 30분이라 20분 예산에 안 들어가고, '
        '뒤따르는 배포까지 같이 잘린다')
    owners = [n for n, j in jobs.items() if _runs_minute_bars(j)]
    assert owners, '분봉을 수집하는 잡이 없다'
    for n in owners:
        t = jobs[n].get('timeout-minutes')
        assert t and t >= 40, (
            f'{n} 잡 타임아웃({t}분)이 실측 30분 + 여유에 못 미친다')


