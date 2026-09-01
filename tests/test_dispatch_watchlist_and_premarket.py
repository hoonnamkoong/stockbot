# -*- coding: utf-8 -*-
"""워치리스트·프리마켓 배치도 태스커가 깨운다.

둘 다 태스커 체인 밖의 네이티브 cron 전용이었고, 실측 지연이 +29분(08-24)에서
+3~11시간(08-27 이후)으로 벌어졌다. 같은 날 같은 레포에서 dispatch 경로는 2분
간격을 정확히 지켰다 — 밀리는 건 cron뿐이다.

지연은 그 자체로도 나쁘지만, **암묵적 안전장치를 무효화한다는 게 더 나쁘다.**
2026-09-01 사고가 그랬다: 22:00 UTC에 돌았어야 할 워치리스트 배치가 3시간 밀려
scraper 창(09:00~15:30 KST) 안으로 들어왔고, 스크래퍼가 그 산출물을 되돌렸다.

cron은 백업으로 남긴다 — 태스커(핸드폰)가 죽었을 때의 경로다.
"""
import datetime as dt
from unittest import mock

import pytest

from scripts import dispatch_premarket_data as pm
from scripts import dispatch_us_eod_watchlist as wl

_KST = dt.timezone(dt.timedelta(hours=9))


def _utc_of(y, mo, d, h, mi):
    """KST 시각을 UTC aware datetime으로."""
    return dt.datetime(y, mo, d, h, mi, tzinfo=_KST).astimezone(dt.timezone.utc)


# 2026-09-01은 화요일 — 워치리스트 창(화~토)과 프리마켓 창(월~금) 둘 다 열린다.
CASES = [
    pytest.param(wl, 'dispatch_us_eod_watchlist', _utc_of(2026, 9, 1, 7, 30), id='watchlist'),
    pytest.param(pm, 'dispatch_premarket_data', _utc_of(2026, 9, 1, 7, 30), id='premarket'),
]


@pytest.mark.parametrize('mod,fn,now', CASES)
def test_창_안에_런이_없으면_부른다(mod, fn, now):
    with mock.patch.object(mod.gh, 'list_runs', return_value=[]), \
         mock.patch.object(mod.gh, 'dispatch', return_value=True) as post:
        assert getattr(mod, fn)(now_utc=now, log=lambda *_: None) == 'dispatched'
    post.assert_called_once()


@pytest.mark.parametrize('mod,fn,now', CASES)
def test_성공한_런이_있으면_생략한다(mod, fn, now):
    ok = [{'created_at': _utc_of(2026, 9, 1, 7, 25).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'status': 'completed', 'conclusion': 'success'}]
    with mock.patch.object(mod.gh, 'list_runs', return_value=ok), \
         mock.patch.object(mod.gh, 'dispatch') as post:
        assert getattr(mod, fn)(now_utc=now, log=lambda *_: None) == 'skipped'
    post.assert_not_called()


@pytest.mark.parametrize('mod,fn,now', CASES)
def test_실패한_런은_간격이_지나면_재시도한다(mod, fn, now):
    """cron 백업이 07:00에 떠서 죽었으면, 태스커가 그걸 이어받아야 한다."""
    bad = [{'created_at': _utc_of(2026, 9, 1, 7, 25).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'status': 'completed', 'conclusion': 'failure'}]
    later = _utc_of(2026, 9, 1, 7, 55)         # 30분 뒤 — 간격(25분) 지났다
    with mock.patch.object(mod.gh, 'list_runs', return_value=bad), \
         mock.patch.object(mod.gh, 'dispatch', return_value=True) as post:
        assert getattr(mod, fn)(now_utc=later, log=lambda *_: None) == 'dispatched'
    post.assert_called_once()


@pytest.mark.parametrize('mod,fn,now', CASES)
def test_조회_실패면_부르지_않는다(mod, fn, now):
    """중복 런은 db-data push에서 서로 밟는다. 모르면 시끄러운 쪽이 아니라
    조용한 쪽으로 실패한다 — dispatch_eod_data와 같은 관례다."""
    with mock.patch.object(mod.gh, 'list_runs', return_value=None), \
         mock.patch.object(mod.gh, 'dispatch') as post:
        assert getattr(mod, fn)(now_utc=now, log=lambda *_: None) == 'skipped'
    post.assert_not_called()


@pytest.mark.parametrize('mod,fn,now', CASES)
def test_어제_런은_오늘_치가_아니다(mod, fn, now):
    """`since`가 오늘 창 시작이라, 어제 성공한 런이 오늘 발화를 막으면 안 된다."""
    old = [{'created_at': _utc_of(2026, 8, 31, 7, 25).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'status': 'completed', 'conclusion': 'success'}]
    with mock.patch.object(mod.gh, 'list_runs', return_value=old), \
         mock.patch.object(mod.gh, 'dispatch', return_value=True) as post:
        assert getattr(mod, fn)(now_utc=now, log=lambda *_: None) == 'dispatched'
    post.assert_called_once()


def test_두_스크립트가_서로_다른_워크플로를_부른다():
    """복사해 만들었으므로 워크플로 이름을 안 바꾸는 실수가 가장 흔하다."""
    assert wl._WORKFLOW == 'us_eod_watchlist.yml'
    assert pm._WORKFLOW == 'premarket_data.yml'
