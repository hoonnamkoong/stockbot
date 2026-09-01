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

from scripts.dispatch_eod_data import _MAX_ATTEMPTS, should_skip  # noqa: E402

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
    """태스커가 2분마다 들어온다 — 상한이 없으면 지속 장애에서 30번 깨운다."""
    runs = [_run((16, i), 'failure') for i in range(0, _MAX_ATTEMPTS * 5, 5)]
    skip, why = should_skip(runs, NOW)
    assert skip and '상한' in why and '사람이 봐야' in why


def test_one_below_the_cap_still_retries():
    runs = [_run((16, i), 'failure') for i in range(0, (_MAX_ATTEMPTS - 1) * 5, 5)]
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
