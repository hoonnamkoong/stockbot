# -*- coding: utf-8 -*-
"""장 마감 뒤 EOD 배치(eod_data.yml)를 깨운다.

    python3 scripts/dispatch_eod_data.py

eod_data.yml의 `0 7 * * 1-5` cron은 평소 40~57분 지연이었는데 2026-08-27부터
**11~12시간**으로 벌어졌다(08-27 18:06 UTC, 08-28 19:16 UTC). us_trading의 cron이
0건으로 죽은 것과 같은 날이다.

이 배치는 심9-1(돈치안)·심11(미너비니)의 **다음 세션 감시목록**을 만든다. 지연이
다음 09:00 KST를 넘기면 두 심이 그 세션을 통째로 잃는다 — 워크플로 주석의
"마감 후 작업이라 지연이 무해하다"는 전제가 틀렸다. 08-27에는 실제로 안 떠서
사람이 수동 dispatch했다.

태스커 창(09:00~06:00 KST)이 마감 직후를 덮으므로 그 신호로 깨운다. cron은 남는다.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts import gh_dispatch as gh  # noqa: E402

_WORKFLOW = 'eod_data.yml'
_KST = dt.timezone(dt.timedelta(hours=9))
# 장 마감. 이 시각 **뒤에** 시작한 런만 종가를 담는다 — eod_data.yml 자체가
# 장중(UTC < 06:30)이면 수집을 건너뛰는 게이트를 갖고 있다.
_KR_CLOSE_HHMM = (15, 30)


# 재시도 상한과 간격. 판정 자체는 gh_dispatch.should_skip에 있다 —
# us_eod_watchlist·premarket도 같은 판정을 쓰므로 세 벌로 복사하지 않는다.
_MAX_ATTEMPTS = 6
_RETRY_COOLDOWN_MIN = 25


def should_skip(runs: list[dict], now_kst: dt.datetime) -> tuple[bool, str]:
    """(생략할까, 이유). **오늘 마감 이후**의 런만 본다.

    창 시작(16:00)이 아니라 마감(15:30)을 기준으로 삼는다 — 장중에 돈 런은
    eod_data.yml의 게이트에 막혀 종가를 안 쓰므로 '돌았다'로 치면 안 된다.
    """
    close = now_kst.replace(hour=_KR_CLOSE_HHMM[0], minute=_KR_CLOSE_HHMM[1],
                            second=0, microsecond=0)
    return gh.should_skip(runs, now_kst, close,
                          max_attempts=_MAX_ATTEMPTS,
                          cooldown_min=_RETRY_COOLDOWN_MIN)


def already_ran(created_ats: list[str], now_kst: dt.datetime) -> bool:
    """[구] 오늘 마감 이후에 시작한 런이 있는가.

    성공 여부를 못 봐서 실패한 런이 재시도를 막았다. `should_skip`이 대신한다.
    남겨 둔 이유는 기존 테스트가 이 경계 계산을 고정하고 있어서다.
    """
    close = now_kst.replace(hour=_KR_CLOSE_HHMM[0], minute=_KR_CLOSE_HHMM[1],
                            second=0, microsecond=0)
    for raw in created_ats:
        ts = dt.datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if ts.astimezone(_KST) >= close:
            return True
    return False


def dispatch_eod_data(now_utc: dt.datetime | None = None, log=print) -> str:
    """'dispatched' | 'skipped' | 'failed'."""
    now_kst = (now_utc or dt.datetime.now(dt.timezone.utc)).astimezone(_KST)

    runs = gh.list_runs(_WORKFLOW, log=log)
    if runs is None:
        # 조회 실패는 생략 쪽이다. 중복 EOD 런은 db-data push에서 서로 밟는다.
        log('[EOD-Dispatch] 런 목록 확인 불가 — 생략')
        return 'skipped'
    skip, why = should_skip(runs, now_kst)
    if skip:
        log(f'[EOD-Dispatch] 생략 — {why}')
        return 'skipped'

    log(f'[EOD-Dispatch] 발화 — {why}')
    return 'dispatched' if gh.dispatch(_WORKFLOW, log=log) else 'failed'


if __name__ == '__main__':
    dispatch_eod_data()
