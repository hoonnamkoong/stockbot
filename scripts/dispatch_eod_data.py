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


# 실패한 배치를 몇 번까지 다시 깨울지. 태스커가 창(16:00~17:00) 안에서 2분마다
# 들어오므로 상한이 없으면 지속 장애 시 30번 디스패치한다.
_MAX_ATTEMPTS = 3


def should_skip(runs: list[dict], now_kst: dt.datetime) -> tuple[bool, str]:
    """(생략할까, 이유). 오늘 마감 이후의 런만 본다.

    **성공한 런이 있을 때만 '이미 돌았다'로 본다.** 예전에는 시작 시각만 보고
    판단해서, 2026-09-01에 KIS 타임아웃으로 죽은 EOD 배치가 **자기 재시도를
    스스로 막았다.** 그날 심9-1·심11의 다음 세션 감시목록이 안 만들어졌고,
    그건 두 심이 다음 날을 통째로 잃는다는 뜻이다.

    다만 무한 재시도는 안 된다 — 태스커가 2분마다 들어오므로 지속 장애에서
    수십 번 깨우게 된다. 실패 횟수에 상한을 둔다.
    """
    close = now_kst.replace(hour=_KR_CLOSE_HHMM[0], minute=_KR_CLOSE_HHMM[1],
                            second=0, microsecond=0)
    today = [r for r in runs
             if dt.datetime.fromisoformat(
                 r['created_at'].replace('Z', '+00:00')).astimezone(_KST) >= close]

    if any(r.get('conclusion') == 'success' for r in today):
        return True, '오늘 성공한 런이 있다'
    if any(r.get('status') in ('queued', 'in_progress') for r in today):
        return True, '지금 돌고 있다'

    failed = [r for r in today if r.get('conclusion') not in (None, 'success')]
    if len(failed) >= _MAX_ATTEMPTS:
        # 여기서 조용히 멈추면 안 된다 — 감시목록이 없는 채로 다음 세션에 들어간다.
        return True, f'오늘 {len(failed)}회 실패 — 상한({_MAX_ATTEMPTS}) 도달, 사람이 봐야 한다'
    if failed:
        return False, f'오늘 {len(failed)}회 실패 — 재시도한다'
    return False, '오늘 마감 뒤 런이 없다'


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
