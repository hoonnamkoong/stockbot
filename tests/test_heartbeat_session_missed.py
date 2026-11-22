# -*- coding: utf-8 -*-
"""장외 판정이 '세션을 통째로 빼먹었다'를 가리지 못하게 한다.

2026-11-05 12:46 KST ~ 11-10 04:40 KST, 태스커가 멈춰 봇 전체가 죽었다.
금요일(11-06)과 월요일(11-09) 두 세션을 통째로 잃었고 그동안 프로그램 매매는
켜져 있었다. 감시자는 11-06에 두 번 돌면서 이렇게 찍었다:

    [Heartbeat] 판정=off_session 마지막완주=2026-11-05 12:49 KST 거래일=True 지금=21:37 KST

**마지막 완주가 33시간 전이라는 증거를 손에 들고 침묵했다.** `judge()`가
`beat_at`을 보기도 전에 `OFF_SESSION`으로 빠져나가기 때문이다. 그 조기 반환은
"지금 돌고 있나"에는 맞지만 **"지난 세션을 돌았나"에는 틀리다.**

왜 장중에 안 잡혔나도 같이 봐야 한다. 네이티브 cron은 `0 0-6 * * 1-5`
(09:00~15:00 KST)인데 그날 배달된 두 런은 21:37 KST(12:37 UTC)였다 —
**GitHub이 cron을 장외로 늦게 배달한다.** 즉 장중 감시가 장외로 밀리면 지금
구조에서는 아무 말도 안 하게 된다.

거짓 경보를 안 내는 근거: trading.yml은 장 밖에서도 돈다(EOD·미국 세션).
정상인 날 마지막 완주는 **익일 08:00 KST**로 실측됐다(11-13·17·18·19·20
다섯 거래일 전부). 그래서 "마지막 완주가 지난 세션 개장보다 앞선다"는 조건은
정상인 날에 걸릴 수 없다.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src import heartbeat  # noqa: E402

_KST = dt.timezone(dt.timedelta(hours=9))


def kst(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=_KST)


# 2026-11-02(월) ~ 11-10(화). 11-07·08은 주말.
CAL = {'20261102': 'Y', '20261103': 'Y', '20261104': 'Y', '20261105': 'Y',
       '20261106': 'Y', '20261107': 'N', '20261108': 'N', '20261109': 'Y',
       '20261110': 'Y'}


# ── 지난 세션이 언제인지 ───────────────────────────────────────────

def test_그날_세션이_끝났으면_그날이_마지막_세션이다():
    assert heartbeat.last_closed_session(kst(2026, 11, 6, 21, 37), CAL) == '20261106'


def test_세션이_아직_안_끝났으면_오늘은_후보가_아니다():
    """09:00~15:50 사이에 '오늘 세션을 빼먹었다'고 물으면 매일 아침 거짓이다."""
    assert heartbeat.last_closed_session(kst(2026, 11, 6, 10, 30), CAL) == '20261105'


def test_마감_정각은_끝난_것으로_센다():
    assert heartbeat.last_closed_session(kst(2026, 11, 6, 15, 50), CAL) == '20261106'


def test_주말과_휴장일은_건너뛴다():
    assert heartbeat.last_closed_session(kst(2026, 11, 8, 20, 0), CAL) == '20261106'


def test_달력에_구멍이_있으면_모른다고_한다():
    """모르는 채로 '세션을 빼먹었다'고 알리면 공휴일마다 거짓 경보가 난다."""
    assert heartbeat.last_closed_session(kst(2026, 11, 6, 21, 37), {}) is None


# ── 판정 ───────────────────────────────────────────────────────────

def test_장외여도_지난_세션을_통째로_빼먹었으면_알린다():
    """실제 사고의 재현 — 이 입력으로 off_session이 나오면 나흘을 또 잃는다."""
    state = heartbeat.judge(kst(2026, 11, 6, 21, 37), kst(2026, 11, 5, 12, 49),
                            trading_day=True, last_session='20261106')
    assert state == heartbeat.SESSION_MISSED


def test_지난_세션에_한_번이라도_완주했으면_장외는_조용하다():
    state = heartbeat.judge(kst(2026, 11, 6, 21, 37), kst(2026, 11, 6, 9, 2),
                            trading_day=True, last_session='20261106')
    assert state == heartbeat.OFF_SESSION


def test_장외_완주도_세션_안의_완주가_아니면_안_센다():
    """전날 밤 23시 EOD 런은 그날 세션을 돌았다는 증거가 아니다."""
    state = heartbeat.judge(kst(2026, 11, 6, 21, 37), kst(2026, 11, 5, 23, 10),
                            trading_day=True, last_session='20261106')
    assert state == heartbeat.SESSION_MISSED


def test_완주가_아예_없으면_세션_결손이다():
    state = heartbeat.judge(kst(2026, 11, 6, 21, 37), None,
                            trading_day=True, last_session='20261106')
    assert state == heartbeat.SESSION_MISSED


def test_지난_세션을_모르면_장외_판정을_유지한다():
    state = heartbeat.judge(kst(2026, 11, 6, 21, 37), kst(2026, 11, 5, 12, 49),
                            trading_day=True, last_session=None)
    assert state == heartbeat.OFF_SESSION


def test_주말에도_직전_거래_세션을_본다():
    """금요일을 빼먹었으면 토요일에 알아도 월요일보다 이르다."""
    state = heartbeat.judge(kst(2026, 11, 7, 11, 0), kst(2026, 11, 5, 12, 49),
                            trading_day=False, last_session='20261106')
    assert state == heartbeat.SESSION_MISSED


def test_장중_판정은_건드리지_않는다():
    """'지금 멎었다'는 여전히 STALE이다 — 메시지도 조치도 다르다."""
    now = kst(2026, 11, 6, 10, 30)
    beat = now - dt.timedelta(minutes=heartbeat.MAX_AGE_MIN + 1)
    assert heartbeat.judge(now, beat, trading_day=True,
                           last_session='20261105') == heartbeat.STALE


# ── 감시 스크립트 배선 ─────────────────────────────────────────────
# 판정이 맞아도 알림이 나갈 수 없으면 감시가 없는 것과 같다.

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import check_heartbeat as chk  # noqa: E402


def _wire(monkeypatch, runs, now, trading_day=True, cal=None):
    sent = []
    monkeypatch.setattr(chk, 'fetch_runs', lambda log=print: runs)
    monkeypatch.setattr(chk, 'load_calendar', lambda: cal if cal is not None else CAL)
    monkeypatch.setattr(chk, 'lookup', lambda days, ymd: trading_day)
    monkeypatch.setattr(chk.alerts, 'send_alert',
                        lambda text, log=print: sent.append(text))

    class _Now(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return now
    monkeypatch.setattr(chk.dt, 'datetime', _Now)
    return sent


def test_세션_결손이면_실제로_알림이_나간다(monkeypatch):
    # 2026-11-05 03:49Z = 11-05 12:49 KST. 그 뒤로 완주가 없다.
    runs = [{'conclusion': 'success', 'updated_at': '2026-11-05T03:49:00Z'}]
    sent = _wire(monkeypatch, runs, now=kst(2026, 11, 6, 21, 37))

    assert chk.main(log=lambda *a: None) == 0
    assert len(sent) == 1, f'알림이 안 나갔다: {sent}'
    assert '2026-11-06' in sent[0], f'빼먹은 세션이 본문에 없다: {sent[0]}'
    assert '2026-11-05 12:49' in sent[0], f'마지막 완주가 본문에 없다: {sent[0]}'


def test_지난_세션을_돌았으면_장외에_조용하다(monkeypatch):
    runs = [{'conclusion': 'success', 'updated_at': '2026-11-06T00:02:00Z'}]
    sent = _wire(monkeypatch, runs, now=kst(2026, 11, 6, 21, 37))

    assert chk.main(log=lambda *a: None) == 0
    assert sent == []


def test_달력이_없으면_장외에_조용하다(monkeypatch):
    """달력 결손은 신선도 감사의 몫이다 — 여기서 거짓 경보로 바꾸지 않는다."""
    runs = [{'conclusion': 'success', 'updated_at': '2026-11-05T03:49:00Z'}]
    sent = _wire(monkeypatch, runs, now=kst(2026, 11, 6, 21, 37), cal={})

    assert chk.main(log=lambda *a: None) == 0
    assert sent == []
