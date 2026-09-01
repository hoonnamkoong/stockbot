# -*- coding: utf-8 -*-
"""태스커가 깨우는 배치의 공통 재시도 판정.

`dispatch_eod_data.py`가 2026-09-01 하루에 세 번 고쳐진 자리다. 세 번 다 같은
계열이었다 — ① 실패한 런이 시작 시각만으로 '이미 돌았다'로 읽혀 자기 재시도를
막았다, ② 재시도를 열었더니 창이 1시간뿐이라 몇 시간짜리 장애를 못 버텼다,
③ 창을 넓혔더니 매달린 런(`in_progress`)이 재시도를 막았다.

`us_eod_watchlist`·`premarket_data`도 같은 cron 지연에 노출돼 있어 같은 판정이
필요하다. 세 벌로 복사하면 다음 교훈이 한 곳에만 반영된다 — 그래서 여기 모은다.

**상한과 간격은 같이 있어야 한다.** 상한만 있으면 장애 초반 몇 분에 다 쓰고,
간격만 있으면 밤새 깨운다.
"""
import datetime as dt

from scripts import gh_dispatch as gh

_KST = dt.timezone(dt.timedelta(hours=9))


def _kst(y, mo, d, h, mi):
    return dt.datetime(y, mo, d, h, mi, tzinfo=_KST)


def _run(created_at, status='completed', conclusion='failure'):
    return {'created_at': created_at, 'status': status, 'conclusion': conclusion}


NOW = _kst(2026, 9, 1, 17, 0)
SINCE = _kst(2026, 9, 1, 15, 30)


def test_창_안에_런이_없으면_부른다():
    skip, why = gh.should_skip([], NOW, SINCE)
    assert skip is False
    assert why


def test_성공한_런이_있으면_생략한다():
    runs = [_run('2026-09-01T07:00:00Z', conclusion='success')]   # 16:00 KST
    skip, _ = gh.should_skip(runs, NOW, SINCE)
    assert skip is True


def test_돌고_있으면_생략한다():
    runs = [_run('2026-09-01T07:50:00Z', status='in_progress', conclusion=None)]
    skip, _ = gh.should_skip(runs, NOW, SINCE)
    assert skip is True


def test_실패한_런은_간격이_지나면_재시도한다():
    """실패가 자기 재시도를 막으면 안 된다 — 2026-09-01의 첫 번째 고장."""
    runs = [_run('2026-09-01T06:30:00Z')]                          # 15:30 KST, 90분 전
    skip, why = gh.should_skip(runs, NOW, SINCE)
    assert skip is False
    assert '재시도' in why


def test_실패_직후에는_간격을_둔다():
    """간격이 없으면 상한 6회를 12분에 소진하고, 그 뒤 회복해도 안 깨운다."""
    runs = [_run('2026-09-01T07:50:00Z')]                          # 16:50 KST, 10분 전
    skip, why = gh.should_skip(runs, NOW, SINCE)
    assert skip is True
    assert '간격' in why


def test_상한에_닿으면_멈추고_사람을_부른다():
    runs = [_run(f'2026-09-01T07:0{i}:00Z') for i in range(6)]   # 16:0x KST
    skip, why = gh.should_skip(runs, NOW, SINCE)
    assert skip is True
    assert '사람' in why


def test_창_앞의_런은_세지_않는다():
    """장중에 돈 런은 게이트에 막혀 종가를 안 쓴다 — 없는 것과 같다."""
    runs = [_run('2026-09-01T05:00:00Z', conclusion='success')]    # 14:00 KST
    skip, _ = gh.should_skip(runs, NOW, SINCE)
    assert skip is False


def test_취소된_런도_시도로_센다():
    """기존 EOD 판정의 동작을 그대로 옮긴다 — `conclusion`이 success도 None도
    아니면 시도로 센다(cancelled 포함).

    이게 최선인지는 별개 문제다. 2026-09-01 EOD는 cancelled 5 + failure 2 = 7로
    상한(6)에 조기 도달해 그날 재시도가 막혔다. 다만 여기서 바꾸면 이 이관이
    동작 변경을 겸하게 되므로, 판정은 그대로 두고 옮기기만 한다.
    """
    runs = [_run('2026-09-01T07:00:00Z', conclusion='cancelled')]  # 16:00 KST
    skip, why = gh.should_skip(runs, NOW, SINCE)
    assert skip is False, why          # 1회뿐이라 간격만 지나면 재시도한다
    assert '1회 실패' in why, why      # 그러나 '시도 없음'이 아니라 실패로 세었다


def test_간격과_상한은_호출자가_정한다():
    runs = [_run('2026-09-01T06:50:00Z')]                          # 15:50 KST, 70분 전
    assert gh.should_skip(runs, NOW, SINCE, cooldown_min=120)[0] is True
    assert gh.should_skip(runs, NOW, SINCE, cooldown_min=25)[0] is False
    assert gh.should_skip(runs, NOW, SINCE, max_attempts=1)[0] is True
