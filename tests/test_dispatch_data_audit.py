# -*- coding: utf-8 -*-
"""신선도 감사는 하루 한 번만 나간다.

감사 창은 09:00~09:30 KST인데 태스커는 2분마다 때린다 — 그대로 두면 같은 알림이
하루 15통이다. 도배는 침묵과 같다.
"""
import datetime as dt
from unittest import mock

from scripts import dispatch_data_audit as d

_KST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime(2026, 8, 31, 9, 10, tzinfo=_KST).astimezone(dt.timezone.utc)


def test_오늘_아직_안_돌았으면_부른다():
    with mock.patch.object(d.gh, 'ran_since', return_value=False), \
         mock.patch.object(d.gh, 'dispatch', return_value=True) as post:
        assert d.dispatch_data_audit(now_utc=NOW, log=lambda *_: None) == 'dispatched'
    post.assert_called_once()


def test_오늘_이미_돌았으면_생략한다():
    with mock.patch.object(d.gh, 'ran_since', return_value=True), \
         mock.patch.object(d.gh, 'dispatch') as post:
        assert d.dispatch_data_audit(now_utc=NOW, log=lambda *_: None) == 'skipped'
    post.assert_not_called()


def test_조회_실패면_부르지_않는다():
    """중복 발사는 같은 알림을 두 번 보내 신뢰를 깎는다."""
    with mock.patch.object(d.gh, 'ran_since', return_value=None), \
         mock.patch.object(d.gh, 'dispatch') as post:
        assert d.dispatch_data_audit(now_utc=NOW, log=lambda *_: None) == 'skipped'
    post.assert_not_called()


def test_경계는_오늘_자정_KST다():
    """어제 09:10에 돈 런이 오늘 것으로 오해되면 감사가 영영 안 돈다."""
    seen = {}

    def fake(wf, since, log=None):
        seen['since'] = since
        return False

    with mock.patch.object(d.gh, 'ran_since', side_effect=fake), \
         mock.patch.object(d.gh, 'dispatch', return_value=True):
        d.dispatch_data_audit(now_utc=NOW, log=lambda *_: None)
    assert seen['since'].astimezone(_KST).strftime('%Y-%m-%d %H:%M') == '2026-08-31 00:00'
