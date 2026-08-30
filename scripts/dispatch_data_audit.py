# -*- coding: utf-8 -*-
"""개장 직후 산출물 신선도 감사(data_audit.yml)를 하루 한 번 깨운다.

    python3 scripts/dispatch_data_audit.py

감사 창은 09:00~09:30 KST인데 태스커는 2분마다 때린다 — 그대로 두면 하루 15통이
나간다. 별도 워크플로로 빼고 "오늘 이미 돌았나"를 먼저 본다(EOD와 같은 패턴).

별도 워크플로인 두 번째 이유: 감사기 자신이 실패하면 그것도 알림이 나가야 하는데,
trading.yml 안의 스텝이면 continue-on-error로 묻히거나 실전 매매를 빨갛게 만든다.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts import gh_dispatch as gh  # noqa: E402

_WORKFLOW = 'data_audit.yml'
_KST = dt.timezone(dt.timedelta(hours=9))


def dispatch_data_audit(now_utc: dt.datetime | None = None, log=print) -> str:
    """'dispatched' | 'skipped' | 'failed'."""
    now_kst = (now_utc or dt.datetime.now(dt.timezone.utc)).astimezone(_KST)
    midnight = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)

    ran = gh.ran_since(_WORKFLOW, midnight, log=log)
    if ran is not False:
        # True(이미 돎)든 None(조회 실패)든 생략한다. 감사는 하루 한 번이면 되고,
        # 중복 발사는 같은 알림을 두 번 보내 신뢰를 깎는다.
        log('[Audit-Dispatch] 오늘 이미 돌았거나 확인 불가 — 생략')
        return 'skipped'

    return 'dispatched' if gh.dispatch(_WORKFLOW, log=log) else 'failed'


if __name__ == '__main__':
    dispatch_data_audit()
