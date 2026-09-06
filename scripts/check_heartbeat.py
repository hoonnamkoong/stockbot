# -*- coding: utf-8 -*-
"""매매 루프가 **지금** 멈춰 있는지 본다.

    python3 scripts/check_heartbeat.py

기존 감시와 겹치지 않는 자리를 메운다:
  - notify_workflow_failure : 런이 빨갛다        → 빠르지만 "안 돈 것"은 못 본다
  - audit_data_freshness    : 어제 산출물이 없다 → 넓지만 하루 한두 번, 세션 단위
  - **여기**                 : 지금 루프가 멎었다 → 장중, 분 단위

2026-09-06에 "봇이 살아 있나"를 사람이 확인하는 데 GitHub API 질의를 열 번
넘게 했다. 답은 런 이력에 있었고, 그걸 자동으로 읽는 것이 이 스크립트다.

**발화는 네이티브 cron이어야 한다.** 감시 대상(trading.yml)이 태스커→Vercel로
깨어나므로, 이 감시자를 같은 경로에 두면 폰이 죽을 때 감지기도 같이 죽는다 —
data_audit_backup.yml이 같은 이유로 존재한다. cron이 통째로 안 뜨면 이 감시도
조용하다. 그건 못 막는다.
"""
import datetime as dt
import json
import os
import sys
from urllib import error, request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src import alerts, heartbeat  # noqa: E402
from src.market_calendar import load_calendar, lookup  # noqa: E402

_KST = dt.timezone(dt.timedelta(hours=9))
_WATCHED = 'trading.yml'


def _repo():
    return os.environ.get('GITHUB_REPOSITORY') or 'hoonnamkoong/stockbot'


def fetch_runs(log=print) -> list[dict] | None:
    """최근 런 목록. 조회에 실패하면 None — 빈 목록으로 폴백하지 않는다.

    실패를 '런이 없다'로 읽으면 API 장애 때마다 "루프가 죽었다"고 알린다.
    """
    url = (f'https://api.github.com/repos/{_repo()}/actions/workflows/'
           f'{_WATCHED}/runs?per_page=20')
    tok = os.environ.get('GH_PAT') or os.environ.get('GITHUB_TOKEN')
    req = request.Request(url, headers={
        'Authorization': f'token {tok}',
        'Accept': 'application/vnd.github.v3+json'})
    try:
        with request.urlopen(req, timeout=20) as res:
            return json.loads(res.read().decode()).get('workflow_runs', [])
    except (error.URLError, OSError, ValueError) as e:
        log(f'[Heartbeat] 런 목록 조회 실패: {e}')
        return None


def main(log=print) -> int:
    now = dt.datetime.now(_KST)

    runs = fetch_runs(log)
    if runs is None:
        # 측정 불가와 고장은 다르다. 알리지 않고 실패로 끝내 워크플로 실패
        # 알림이 처리하게 한다(연속당 1통 억제가 거기 있다).
        return 1

    beat = heartbeat.last_success_at(runs)
    # 달력이 없거나 낡으면 lookup이 None을 주고 판정은 UNKNOWN이 된다.
    # 그 자체는 여기서 안 알린다 — market_calendar.json은 신선도 감사가
    # 따로 보고 있다(config/data_freshness.yaml, max_age_sessions 3).
    trading_day = lookup(load_calendar(), now.strftime('%Y%m%d'))
    state = heartbeat.judge(now, beat, trading_day)

    # 판정을 반드시 남긴다. 안 남기면 "조용히 통과"와 "아예 안 돌았다"가
    # 로그에서 같은 모양이 된다.
    beat_txt = beat.strftime('%Y-%m-%d %H:%M KST') if beat else '없음'
    log(f'[Heartbeat] 판정={state} 마지막완주={beat_txt} '
        f'거래일={trading_day} 지금={now.strftime("%H:%M")} KST')

    if state != heartbeat.STALE:
        return 0

    age = f'{int((now - beat).total_seconds() // 60)}분 전' if beat else '오늘 한 번도 없음'
    alerts.send_alert(
        f'🫀 매매 루프가 멎었습니다\n'
        f'마지막 완주: {beat_txt} ({age})\n'
        f'임계: {heartbeat.MAX_AGE_MIN}분 / 지금: {now.strftime("%H:%M")} KST\n\n'
        f'{_WATCHED}이 장중인데 트리거를 못 받고 있습니다. '
        f'태스커(폰) → /api/cron 경로를 확인하세요.', log)
    return 0


if __name__ == '__main__':
    sys.exit(main())
