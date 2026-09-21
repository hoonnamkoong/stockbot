# -*- coding: utf-8 -*-
"""/api/cron의 토요일 컷오프가 파이썬 쪽 미국 창과 맞는가.

2026-09-21까지 라우트가 KST 토·일을 통째로 막았다. 미국 금요일장은 KST로
토요일 00:00~05:00(서머타임 해제 시 ~06:00)이라 매주 앞 1시간 30분만 돌았다
(09-04·09-11·09-18 실측). session_router는 토요일 창(미국장·워치리스트)을
이미 알고 있었는데 그 앞단이 막고 있었다.

컷오프는 TS(src/lib/cron-target.ts)에, 창은 파이썬(src/session_gate.py)에 있다.
두 언어로 갈라진 상수는 조용히 어긋난다 — 여기서 묶는다.
"""
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src import session_gate  # noqa: E402
from src.core import clock  # noqa: E402

TARGET_TS = os.path.join(os.path.dirname(__file__), '..', 'src', 'lib', 'cron-target.ts')


def _saturday_close_hour() -> int:
    with open(TARGET_TS, encoding='utf-8') as f:
        m = re.search(r'SATURDAY_CLOSE_HOUR_KST\s*=\s*(\d+)', f.read())
    assert m, 'SATURDAY_CLOSE_HOUR_KST가 cron-target.ts에 없다'
    return int(m.group(1))


def test_토요일_컷오프는_미국_워치리스트_창의_끝이다():
    """컷오프가 창보다 이르면 토요일 워치리스트 배치가 태스커 경로를 잃는다."""
    assert (_saturday_close_hour(), 0) == session_gate.US_WATCHLIST_CLOSE_HHMM


def test_미국_금요일장_전체가_컷오프_전에_끝난다():
    """서머타임·표준시 둘 다. 금요일장의 마지막 분이 토요일 컷오프 전이어야 한다."""
    close_h = _saturday_close_hour()
    for friday in (dt.date(2026, 9, 18), dt.date(2026, 12, 4)):   # EDT / EST
        # 미국 동부 16:00 마감 직전 = UTC로 20:00(EDT) 또는 21:00(EST) 직전.
        for utc_h in range(13, 23):
            now_utc = dt.datetime(friday.year, friday.month, friday.day, utc_h, 0,
                                  tzinfo=dt.timezone.utc)
            if not session_gate.us_session_open(now_utc):
                continue
            kst = now_utc.astimezone(clock.KST)
            if kst.date() > friday:                  # KST로 토요일에 걸친 부분
                assert kst.weekday() == 5
                assert kst.hour < close_h, f'{friday} 미국장 {kst:%H:%M} KST가 컷오프 뒤'


def test_토요일_국내_창은_하나도_열리지_않는다():
    """라우트가 토요일 오전을 통과시키므로 국내 매매를 막는 건 이 게이트들이다."""
    sat = dt.date(2026, 9, 19)
    for h in range(24):
        for m in (0, 30):
            now = dt.datetime(sat.year, sat.month, sat.day, h, m)
            assert not session_gate.kr_session_open(now)
            assert not session_gate.kr_eod_window(now)
            assert not session_gate.kr_audit_window(now)
            assert not session_gate.premarket_window(now)
