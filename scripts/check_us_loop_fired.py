# -*- coding: utf-8 -*-
"""직전 미국 세션 동안 장중 루프가 한 번이라도 발화했는지 확인한다.

    python scripts/check_us_loop_fired.py

2026-08-27~28: us_trading.yml의 `*/5 13-21` cron이 발화를 멈췄다(하루 18회 →
1회 → 0회). 남은 런마저 폐장 뒤라 `[US-Loop] 미국장 시간이 아님 — 종료`로 끝났고,
목·금 세션 거래가 0건이었다. 워크플로는 내내 초록이었다 — **실패가 아니라
미발화**라 Actions에 남는 흔적이 없다.

**감시 대상과 다른 발화 경로에 있어야 한다.** 2026-08-27에 붙인 EOD 미발화
감지기는 장중 루프 안에 있었는데, 미발화가 그 루프 자신에게 일어나자 감지기도
같이 안 돌았다. 그래서 이건 하루 1회짜리 EOD 배치(us_eod_watchlist.yml)에
얹는다 — 태스커와도, trading.yml과도 무관한 경로다.
"""
import datetime as dt
import json
import os
import sys
from urllib import error, request
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src import alerts  # noqa: E402
from src.session_gate import US_CLOSE_HHMM, US_OPEN_HHMM  # noqa: E402

_NY = ZoneInfo('America/New_York')
_WORKFLOW = 'us_trading.yml'


def session_window_utc(now_utc: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """now_utc가 속한 ET 날짜의 정규장 구간을 UTC로 돌려준다.

    이 배치는 22:00 UTC에 도는데 그 시각의 ET 날짜는 같은 UTC 날짜다
    (EDT 18:00 / EST 17:00) — 그래서 '직전 세션' = '오늘 ET 세션'이다.
    """
    et = now_utc.astimezone(_NY)
    start = et.replace(hour=US_OPEN_HHMM[0], minute=US_OPEN_HHMM[1],
                       second=0, microsecond=0)
    end = et.replace(hour=US_CLOSE_HHMM[0], minute=US_CLOSE_HHMM[1],
                     second=0, microsecond=0)
    return start.astimezone(dt.timezone.utc), end.astimezone(dt.timezone.utc)


def count_in_window(created_ats: list[str], start: dt.datetime, end: dt.datetime) -> int:
    n = 0
    for raw in created_ats:
        ts = dt.datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if start <= ts < end:
            n += 1
    return n


def list_runs() -> list[str]:
    """최근 런 100건의 생성 시각. '0건인가'만 보면 되므로 한 페이지면 충분하다."""
    token = os.environ.get('GH_PAT') or os.environ.get('GITHUB_TOKEN')
    repo = os.environ.get('GITHUB_REPOSITORY') or 'hoonnamkoong/stockbot'
    url = (f'https://api.github.com/repos/{repo}/actions/workflows/'
           f'{_WORKFLOW}/runs?per_page=100')
    req = request.Request(url, headers={
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'})
    with request.urlopen(req, timeout=20) as res:
        data = json.loads(res.read().decode())
    return [r['created_at'] for r in data.get('workflow_runs', [])]


def check(now_utc: dt.datetime | None = None, list_runs=list_runs,
          send=None, log=print) -> int:
    """직전 세션의 발화 수. 조회 실패는 -1(알림 없음)."""
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    send = send or (lambda text: alerts.send_alert(text, log=log))
    start, end = session_window_utc(now_utc)
    try:
        created = list_runs()
    except (error.URLError, OSError, ValueError, KeyError) as e:
        # 조회 실패를 0건으로 뭉뚱그리면 감지기가 늑대소년이 되고, 진짜 미발화
        # 알림까지 무시된다.
        log(f'[US-Fired] 런 목록 조회 실패 — 판정 생략: {e}')
        return -1

    n = count_in_window(created, start, end)
    window = f"{start.strftime('%H:%M')}~{end.strftime('%H:%M')} UTC"
    log(f'[US-Fired] {start:%Y-%m-%d} 세션({window}) 발화 {n}건')
    if n == 0:
        send(
            '<b>US 장중 루프가 한 번도 안 돌았습니다</b>\n\n'
            f"{start:%Y-%m-%d} 미국 세션({window}) 동안 <code>{_WORKFLOW}</code> "
            '런이 0건입니다.\n'
            '미국 심은 그 세션에 매매도 손절도 하지 않았습니다.\n\n'
            '확인 순서: ① 태스커가 09:00~06:00 KST 트리거를 보내고 있나 '
            '② trading.yml 라우팅 스텝의 us 판정 ③ us_trading.yml 백업 cron.')
    return n


if __name__ == '__main__':
    check()
