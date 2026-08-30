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

직전 **완료** 런의 결과를 보고 그것도 실패였으면 생략한다. 상태 파일이 필요 없고
(런이 깨진 상황에서 db-data 왕복은 못 믿는다), 사람이 알고 싶은 사건
'언제부터 깨졌나'와 맞는다.

표준 라이브러리만 쓴다 — 실패 지점이 pip install일 수도 있다.
"""
import json
import os
import sys
from urllib import error, parse, request


def should_notify(runs: list[dict] | None, current_run_id: int) -> bool:
    """이번 실패가 '새 소식'인가.

    runs=None(조회 실패)이면 True — 억제를 못 하겠으면 시끄러운 쪽으로 실패한다.
    """
    if runs is None:
        return True
    for r in runs:
        if int(r.get('id', 0)) == int(current_run_id):
            continue                        # 자기 자신
        if r.get('status') != 'completed':
            continue                        # 동시에 도는 런은 직전이 아니다
        # cancelled·skipped는 고장이 아니다. 그 뒤 첫 실패는 새 소식이다.
        return r.get('conclusion') != 'failure'
    return True


def _fetch_runs(wf: str, log) -> list[dict] | None:
    tok = os.environ.get('GH_PAT') or os.environ.get('GITHUB_TOKEN')
    repo = os.environ.get('GITHUB_REPOSITORY') or 'hoonnamkoong/stockbot'
    if not tok or not wf:
        return None
    url = (f'https://api.github.com/repos/{repo}/actions/workflows/{wf}'
           f'/runs?per_page=10')
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
        log(f'[Notify] 직전 런도 실패 — 연속 실패로 보고 알림 생략 ({wf})')
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
