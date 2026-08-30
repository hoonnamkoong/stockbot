# -*- coding: utf-8 -*-
"""미국 장중 루프 미발화 감지기.

2026-08-27~28에 us_trading.yml cron이 발화를 멈춰 목·금 세션 거래가 0건이었는데
이틀을 아무도 몰랐다. 실패가 아니라 미발화라 Actions에 빨간 X가 없었다.

**왜 us_eod_watchlist.yml에 붙는가.** 08-27에 붙였던 EOD 미발화 감지기는 장중
루프 **안에** 있었다 — 미발화가 그 루프 자신에게 일어나면 감지기도 같이 안 돈다.
감지기는 감시 대상과 다른 발화 경로에 있어야 한다. 이 배치는 하루 1회 cron이고
태스커·trading.yml과 무관하다.
"""
import datetime as dt

from scripts import check_us_loop_fired as c


def _utc(y, mo, d, h, mi):
    return dt.datetime(y, mo, d, h, mi, tzinfo=dt.timezone.utc)


def test_세션창은_서머타임을_따라간다():
    # EDT(2026-08-28): 09:30~16:00 ET = 13:30~20:00 UTC
    start, end = c.session_window_utc(_utc(2026, 8, 28, 22, 0))
    assert (start.hour, start.minute) == (13, 30)
    assert (end.hour, end.minute) == (20, 0)
    # EST(2026-01-15): 14:30~21:00 UTC
    start, end = c.session_window_utc(_utc(2026, 1, 15, 22, 0))
    assert (start.hour, start.minute) == (14, 30)
    assert (end.hour, end.minute) == (21, 0)


def test_세션_밖_런은_세지_않는다():
    """08-28 실제 상황: 유일한 런이 22:44 UTC(폐장 뒤)였다."""
    runs = ['2026-08-28T22:44:47Z']
    assert c.count_in_window(runs, *c.session_window_utc(_utc(2026, 8, 28, 22, 0))) == 0


def test_세션_안_런은_센다():
    runs = ['2026-08-28T13:35:00Z', '2026-08-28T19:59:59Z', '2026-08-28T22:44:47Z']
    assert c.count_in_window(runs, *c.session_window_utc(_utc(2026, 8, 28, 22, 0))) == 2


def test_0건이면_알림이_나간다():
    sent = []
    n = c.check(now_utc=_utc(2026, 8, 28, 22, 0),
                list_runs=lambda: ['2026-08-28T22:44:47Z'],
                send=lambda text: sent.append(text), log=lambda *_: None)
    assert n == 0
    assert len(sent) == 1
    assert 'us_trading' in sent[0]


def test_런이_있으면_조용하다():
    sent = []
    n = c.check(now_utc=_utc(2026, 8, 28, 22, 0),
                list_runs=lambda: ['2026-08-28T15:00:00Z'],
                send=lambda text: sent.append(text), log=lambda *_: None)
    assert n == 1
    assert sent == []


def test_조회_실패는_알림으로_때우지_않는다():
    """조회가 죽었는데 '0건'이라고 부르면 감지기가 늑대소년이 된다."""
    sent = []

    def boom():
        raise OSError('api down')

    n = c.check(now_utc=_utc(2026, 8, 28, 22, 0), list_runs=boom,
                send=lambda text: sent.append(text), log=lambda *_: None)
    assert n == -1
    assert sent == []
