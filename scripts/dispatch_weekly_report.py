# -*- coding: utf-8 -*-
"""주간 리포트(weekly_report.yml)를 깨운다.

    python3 scripts/dispatch_weekly_report.py

cron은 `0 9 * * 5`(금 09:00 UTC = 18:00 KST)인데 실측 지연이 +23분에서
**+11시간 27분**(2026-08-28)까지 벌어졌다. 그날 리포트는 금요일 저녁이 아니라
토요일 새벽 05:27에 도착했다.

앞선 두 배치(워치리스트·프리마켓)와 다른 점: 이 시각은 **옛 태스커 창 안**이라
프로파일을 늘리지 않아도 이 배선이 곧바로 동작한다.

cron은 백업으로 남긴다 — 태스커(핸드폰)가 죽었을 때의 경로다.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts import gh_dispatch as gh  # noqa: E402

_WORKFLOW = 'weekly_report.yml'
_KST = dt.timezone(dt.timedelta(hours=9))

# 창 시작(18:00 KST). src.session_gate의 WEEKLY_REPORT_OPEN_HHMM과 같은 값이지만,
# 여기서 그 모듈을 import하면 zoneinfo가 딸려온다 — 이 스크립트는 pip install
# 앞에서 돈다.
_WINDOW_OPEN_HHMM = (18, 0)

# 리포트는 주 1회라 중복 발송이 특히 눈에 띈다(이메일 + 텔레그램). 상한·간격은
# 다른 dispatch와 같은 값을 쓴다.
_MAX_ATTEMPTS = 6
_RETRY_COOLDOWN_MIN = 25


def dispatch_weekly_report(now_utc: dt.datetime | None = None, log=print) -> str:
    """'dispatched' | 'skipped' | 'failed'."""
    now_kst = (now_utc or dt.datetime.now(dt.timezone.utc)).astimezone(_KST)
    since = now_kst.replace(hour=_WINDOW_OPEN_HHMM[0], minute=_WINDOW_OPEN_HHMM[1],
                            second=0, microsecond=0)

    runs = gh.list_runs(_WORKFLOW, log=log)
    if runs is None:
        # 조회 실패는 생략 쪽이다 — 리포트를 두 번 보내는 것이 한 번 늦는 것보다 나쁘다.
        log('[Weekly-Dispatch] 런 목록 확인 불가 — 생략')
        return 'skipped'

    skip, why = gh.should_skip(runs, now_kst, since,
                               max_attempts=_MAX_ATTEMPTS,
                               cooldown_min=_RETRY_COOLDOWN_MIN)
    if skip:
        log(f'[Weekly-Dispatch] 생략 — {why}')
        return 'skipped'

    log(f'[Weekly-Dispatch] 발화 — {why}')
    return 'dispatched' if gh.dispatch(_WORKFLOW, log=log) else 'failed'


if __name__ == '__main__':
    dispatch_weekly_report()
