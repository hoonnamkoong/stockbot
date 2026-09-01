# -*- coding: utf-8 -*-
"""미국장 마감 뒤 워치리스트 배치(us_eod_watchlist.yml)를 깨운다.

    python3 scripts/dispatch_us_eod_watchlist.py

이 워크플로는 태스커 체인 밖의 네이티브 cron(`0 22 * * 1-5`) 전용이었다. 실측
지연이 +29분(08-24)에서 **+3~8시간**(08-27 이후)으로 벌어졌는데, 같은 날 같은
레포에서 dispatch 경로(us_trading)는 2분 간격을 정확히 지켰다 — 밀리는 건 cron뿐이다.

지연 자체보다 나쁜 건 **암묵적 안전장치가 무효화된다**는 점이다. 2026-09-01에
이 배치가 3시간 밀려 01:06 UTC(10:06 KST)에 돌면서 scraper 창(09:00~15:30 KST)
안으로 들어왔고, 스크래퍼가 그 워치리스트를 8분 뒤 되돌렸다. 정시(07:00 KST)에
돌았으면 창 밖이라 만나지도 않았다.

cron은 백업으로 남긴다 — 태스커(핸드폰)가 죽었을 때의 경로다.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts import gh_dispatch as gh  # noqa: E402

_WORKFLOW = 'us_eod_watchlist.yml'
_KST = dt.timezone(dt.timedelta(hours=9))

# 창 시작(07:00 KST). 이 시각 이후의 런만 '오늘 치'로 본다 — src.session_gate의
# US_WATCHLIST_OPEN_HHMM과 같은 값이지만, 여기서 그 모듈을 import하면 zoneinfo가
# 딸려온다. 이 스크립트는 pip install 앞에서 돈다.
_WINDOW_OPEN_HHMM = (7, 0)

# 태스커가 2분마다 들어오므로 상한이 없으면 지속 장애에서 수십 번 dispatch한다.
# 간격이 없으면 상한을 장애 초반 몇 분에 소진한다 — 둘은 같이 있어야 한다.
_MAX_ATTEMPTS = 6
_RETRY_COOLDOWN_MIN = 25


def dispatch_us_eod_watchlist(now_utc: dt.datetime | None = None, log=print) -> str:
    """'dispatched' | 'skipped' | 'failed'."""
    now_kst = (now_utc or dt.datetime.now(dt.timezone.utc)).astimezone(_KST)
    since = now_kst.replace(hour=_WINDOW_OPEN_HHMM[0], minute=_WINDOW_OPEN_HHMM[1],
                            second=0, microsecond=0)

    runs = gh.list_runs(_WORKFLOW, log=log)
    if runs is None:
        # 조회 실패는 생략 쪽이다 — 중복 런은 db-data push에서 서로 밟는다.
        log('[Watchlist-Dispatch] 런 목록 확인 불가 — 생략')
        return 'skipped'

    skip, why = gh.should_skip(runs, now_kst, since,
                               max_attempts=_MAX_ATTEMPTS,
                               cooldown_min=_RETRY_COOLDOWN_MIN)
    if skip:
        log(f'[Watchlist-Dispatch] 생략 — {why}')
        return 'skipped'

    log(f'[Watchlist-Dispatch] 발화 — {why}')
    return 'dispatched' if gh.dispatch(_WORKFLOW, log=log) else 'failed'


if __name__ == '__main__':
    dispatch_us_eod_watchlist()
