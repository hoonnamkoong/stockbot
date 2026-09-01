# -*- coding: utf-8 -*-
"""프리마켓·미국지수 적재(premarket_data.yml)를 깨운다.

    python3 scripts/dispatch_premarket_data.py

`dispatch_us_eod_watchlist.py`와 같은 이유다 — 이 워크플로도 태스커 체인 밖의
네이티브 cron(`20 22 * * 0-4`) 전용이었고, 실측 지연이 +28분(08-24)에서
**+7시간 50분**(08-28)까지 벌어졌다.

여기서는 지연이 곧 결손이다. 산출물이 국내 개장(09:00 KST)을 넘겨 도착하면
그날 프리마켓 판단에는 쓸 수 없다. 그래도 창을 12:00까지 두는 것은
investor_flows.csv를 심13이 장중에 읽기 때문이다 — 늦더라도 빈 것보다 낫다.

cron은 백업으로 남긴다 — 태스커(핸드폰)가 죽었을 때의 경로다.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts import gh_dispatch as gh  # noqa: E402

_WORKFLOW = 'premarket_data.yml'
_KST = dt.timezone(dt.timedelta(hours=9))

# 창 시작(07:20 KST). src.session_gate의 PREMARKET_OPEN_HHMM과 같은 값이지만,
# 여기서 그 모듈을 import하면 zoneinfo가 딸려온다 — 이 스크립트는 pip install
# 앞에서 돈다.
_WINDOW_OPEN_HHMM = (7, 20)

_MAX_ATTEMPTS = 6
_RETRY_COOLDOWN_MIN = 25


def dispatch_premarket_data(now_utc: dt.datetime | None = None, log=print) -> str:
    """'dispatched' | 'skipped' | 'failed'."""
    now_kst = (now_utc or dt.datetime.now(dt.timezone.utc)).astimezone(_KST)
    since = now_kst.replace(hour=_WINDOW_OPEN_HHMM[0], minute=_WINDOW_OPEN_HHMM[1],
                            second=0, microsecond=0)

    runs = gh.list_runs(_WORKFLOW, log=log)
    if runs is None:
        log('[Premarket-Dispatch] 런 목록 확인 불가 — 생략')
        return 'skipped'

    skip, why = gh.should_skip(runs, now_kst, since,
                               max_attempts=_MAX_ATTEMPTS,
                               cooldown_min=_RETRY_COOLDOWN_MIN)
    if skip:
        log(f'[Premarket-Dispatch] 생략 — {why}')
        return 'skipped'

    log(f'[Premarket-Dispatch] 발화 — {why}')
    return 'dispatched' if gh.dispatch(_WORKFLOW, log=log) else 'failed'


if __name__ == '__main__':
    dispatch_premarket_data()
