# -*- coding: utf-8 -*-
"""EOD 배치도 태스커가 깨운다.

eod_data.yml의 `0 7 * * 1-5` cron은 평소 40~57분 지연이었는데 2026-08-27부터
**11~12시간**으로 벌어졌다(08-27 18:06 UTC, 08-28 19:16 UTC). us_trading의 cron이
0건으로 죽은 것과 같은 날, 같은 원인이다.

이 배치는 심9-1(돈치안)·심11(미너비니)의 **다음 세션 감시목록**을 만든다. 지연이
다음 09:00 KST를 넘기면 두 심이 그 세션을 통째로 잃는다. 08-27에는 실제로 안 떠서
사람이 수동 dispatch(14:22 UTC)했다.

원래 워크플로 주석은 "마감 후 작업이라 지연이 무해하다"고 적혀 있었다. 감시목록이
다음 세션 **전에** 있어야 한다는 걸 놓친 전제였다.
"""
import datetime as dt
from unittest import mock

from scripts import dispatch_eod_data as d

_KST = dt.timezone(dt.timedelta(hours=9))


def _kst(y, mo, day, h, mi):
    return dt.datetime(y, mo, day, h, mi, tzinfo=_KST)


def test_마감_뒤_런이_있으면_이미_돈_것():
    now = _kst(2026, 8, 28, 16, 10)
    # 08-28 15:45 KST = 06:45 UTC
    assert d.already_ran(['2026-08-28T06:45:00Z'], now) is True


def test_마감_전_런은_오늘_치가_아니다():
    """장중에 돈 런은 게이트에 막혀 종가를 안 쓴다 — 다시 불러야 한다."""
    now = _kst(2026, 8, 28, 16, 10)
    # 08-28 14:00 KST = 05:00 UTC (장중)
    assert d.already_ran(['2026-08-28T05:00:00Z'], now) is False


def test_어제_런은_오늘_치가_아니다():
    now = _kst(2026, 8, 28, 16, 10)
    assert d.already_ran(['2026-08-27T10:16:00Z'], now) is False


def test_런이_없으면_부른다():
    with mock.patch.object(d.gh, 'list_run_times', return_value=[]), \
         mock.patch.object(d.gh, 'dispatch', return_value=True) as post:
        assert d.dispatch_eod_data(now_utc=_kst(2026, 8, 28, 16, 10).astimezone(dt.timezone.utc),
                                   log=lambda *_: None) == 'dispatched'
    post.assert_called_once()


def test_이미_돌았으면_생략한다():
    with mock.patch.object(d.gh, 'list_run_times', return_value=['2026-08-28T06:45:00Z']), \
         mock.patch.object(d.gh, 'dispatch') as post:
        assert d.dispatch_eod_data(now_utc=_kst(2026, 8, 28, 16, 10).astimezone(dt.timezone.utc),
                                   log=lambda *_: None) == 'skipped'
    post.assert_not_called()


def test_조회_실패면_부르지_않는다():
    """중복 EOD 런은 db-data push에서 서로 밟는다. 놓친 배치는 장중 루프의
    eod_batch_stale 알림이 잡는다 — 그쪽이 이미 있다."""
    with mock.patch.object(d.gh, 'list_run_times', return_value=None), \
         mock.patch.object(d.gh, 'dispatch') as post:
        assert d.dispatch_eod_data(now_utc=_kst(2026, 8, 28, 16, 10).astimezone(dt.timezone.utc),
                                   log=lambda *_: None) == 'skipped'
    post.assert_not_called()
