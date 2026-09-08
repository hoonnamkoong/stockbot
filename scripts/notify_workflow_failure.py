# -*- coding: utf-8 -*-
"""워크플로 실패를 텔레그램으로 알린다 — **실패 연속당 한 번**.

    - name: Notify on failure
      if: failure()
      env: { WORKFLOW_FILE: eod_data.yml, ... }
      run: python3 scripts/notify_workflow_failure.py

2026-08-30 실측: `if: failure()` 알림이 있는 워크플로는 셋뿐이었고 그 셋의 최근
30런 실패는 0이다. 알림이 없는 나머지에만 실패가 쌓여 있었다 — premarket 9/10,
token_refresh 10/30, us_eod_watchlist 2/8. 빨간불이 나도 아무도 안 불러서 몇 주씩
방치됐다.

**런마다 보내면 안 된다.** trading은 하루 196런, us_trading은 태스커 전환 뒤
세션당 100런 남짓이다. 지속 실패에 수백 통이 나가면 사람이 알림을 끄고, 그러면
알림이 없는 것과 같아진다.

억제는 **시간창**으로 잰다. 최근 SUPPRESS_WINDOW_MIN분 안에 이미 성공이 아닌
완료 런이 있으면 보내지 않는다. 상태 파일은 여전히 없다(런이 깨진 상황에서
db-data 왕복은 못 믿는다) — 이미 부르는 API 응답의 타임스탬프만 쓴다.

**왜 '직전 완료 런'이 아니라 시간창인가.** 2026-09-08에 실패 알림이 네 통
나갔다(12:59·14:15·14:24·14:43). 네 번 다 잡 타임아웃에 잘린 `cancelled`인데,
취소가 성공 런들 사이에 산발적으로 끼어 있어서 직전 완료 런이 매번 `success`였다.
직전 한 건만 보는 기준으로는 `cancelled`를 `failure`로 세도 네 통 그대로 나간다 —
연속을 전제한 것이 이 고장 유형과 안 맞았다.

지속 장애에서는 매 런이 직전 실패를 창 안에서 보므로 계속 억제돼 통틀어 한 통이다.
그 성질은 그대로 유지된다.

표준 라이브러리만 쓴다 — 실패 지점이 pip install일 수도 있다.
"""
import datetime as dt
import json
import os
import sys
from urllib import error, parse, request

# 이 창 안에 이미 non-success 완료 런이 있으면 보내지 않는다. trading은 2분
# 간격이라 30분이면 15런이다 — `_fetch_runs`의 per_page가 그보다 넉넉해야
# 창 안을 다 본다.
SUPPRESS_WINDOW_MIN = 30


def _completed_at(run: dict) -> dt.datetime | None:
    """런이 끝난 시각. 못 읽으면 None — 지어내지 않는다."""
    raw = run.get('updated_at')
    if not isinstance(raw, str):
        return None
    try:
        # Python 3.10의 fromisoformat은 'Z'를 못 읽는다(3.11+만 가능).
        return dt.datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return None


def should_notify(runs: list[dict] | None, current_run_id: int,
                  now: dt.datetime | None = None) -> bool:
    """이번 실패가 '새 소식'인가.

    runs=None(조회 실패)이면 True — 억제를 못 하겠으면 시끄러운 쪽으로 실패한다.
    """
    if runs is None:
        return True
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(minutes=SUPPRESS_WINDOW_MIN)
    for r in runs:
        if int(r.get('id', 0)) == int(current_run_id):
            # 자기 자신. 알림 스텝은 잡이 끝나기 전에 도는데 API가 이 런을
            # 이미 non-success로 보고할 수 있다 — 자기 실패로 자기를 억제하면
            # 한 통도 안 간다.
            continue
        if r.get('status') != 'completed':
            continue        # 동시에 도는 런은 결과가 아직 없다
        if r.get('conclusion') == 'success':
            continue
        at = _completed_at(r)
        if at is None:
            return True     # 창 안인지 모르겠으면 억제하지 않는다
        if at >= cutoff:
            return False
    return True


def _fetch_runs(wf: str, log) -> list[dict] | None:
    tok = os.environ.get('GH_PAT') or os.environ.get('GITHUB_TOKEN')
    repo = os.environ.get('GITHUB_REPOSITORY') or 'hoonnamkoong/stockbot'
    if not tok or not wf:
        return None
    # 억제 창(30분)을 덮어야 한다. 가장 빠른 트리거가 2분(trading.yml)이라
    # 창 안에 15런이 들어온다 — 그보다 적게 가져오면 창이 조용히 좁아진다.
    url = (f'https://api.github.com/repos/{repo}/actions/workflows/{wf}'
           f'/runs?per_page=20')
    try:
        req = request.Request(url, headers={
            'Authorization': f'token {tok}',
            'Accept': 'application/vnd.github.v3+json'})
        with request.urlopen(req, timeout=15) as res:
            return json.loads(res.read().decode()).get('workflow_runs', [])
    except (error.URLError, OSError, ValueError) as e:
        log(f'[Notify] 런 이력 조회 실패(알림은 보낸다): {e}')
        return None


def _send(text: str, log) -> bool:
    tok = os.environ['TELEGRAM_BOT_TOKEN']
    chat = os.environ['TELEGRAM_CHAT_ID']
    data = parse.urlencode({'chat_id': chat, 'text': text,
                            'parse_mode': 'HTML'}).encode()
    try:
        with request.urlopen(
                request.Request(f'https://api.telegram.org/bot{tok}/sendMessage',
                                data=data, method='POST'), timeout=15):
            pass
    except (error.URLError, OSError) as e:
        log(f'[Notify] 텔레그램 발송 실패: {e}')
        return False
    return True


def main(log=print) -> str:
    if not (os.environ.get('TELEGRAM_BOT_TOKEN') and os.environ.get('TELEGRAM_CHAT_ID')):
        log('[Notify] 텔레그램 시크릿 없음 — 알림 생략')
        return 'no-telegram'

    wf = os.environ.get('WORKFLOW_FILE', '')
    run_id = os.environ.get('GITHUB_RUN_ID', '0')
    if not should_notify(_fetch_runs(wf, log), run_id):
        log(f'[Notify] 최근 {SUPPRESS_WINDOW_MIN}분 안에 이미 실패가 있었다 — '
            f'같은 장애로 보고 알림 생략 ({wf})')
        return 'suppressed'

    name = os.environ.get('GITHUB_WORKFLOW', wf or '알 수 없는 워크플로')
    url = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
           f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{run_id}")
    ok = _send(f'🚨 <b>{name} 실패</b>\n\n'
               f'{wf} 런이 실패했습니다.\n'
               f'(연속 실패면 이 알림은 한 번만 갑니다)\n\n{url}', log)
    return 'sent' if ok else 'send-failed'


if __name__ == '__main__':
    main()
    sys.exit(0)   # 알림 실패가 워크플로 결과를 또 바꾸지 않는다
