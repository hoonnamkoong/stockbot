"""비공개 레포(stockbot-secret) 파일을 GitHub contents API로 직접 읽고 쓴다.

왜 git이 아니라 API인가:
  실거래 기록(order_history.json, trade_history_real.csv)의 writer가 어느
  워크플로인지는 **선택 심에 따라 바뀐다**. 버즈 불필요 심이면 trading.yml(60초
  루프)이, 버즈 필요 심이면 scraper.yml(10분)이 주문을 낸다. 두 워크플로는
  concurrency 그룹이 달라 동시에 돌 수 있고, 각자 런 시작 시점의 사본을 git으로
  밀면 나중에 끝난 쪽이 먼저 기록된 주문을 덮어써 지운다(lost update).

  워크플로가 만지지 않고 주문 낸 프로세스가 직접 기록하면 writer 경로가 하나가
  되어 이 문제가 사라진다. 원장(program_positions.json)이 이미 같은 이유로
  이 방식을 쓴다 — scraper.yml의 배포 스텝이 그 파일을 명시적으로 제외한다.

실패는 예외를 올리지 않는다. 주문은 이미 나갔고, 기록 실패로 후속 처리를
멈추면 더 나빠진다. 대신 조용히 넘어가지 않고 크게 남긴다.
"""

import base64
import json
import os

import requests

_OWNER = 'hoonnamkoong'
_REPO = 'stockbot-secret'
_BRANCH = 'main'
_TIMEOUT = 10
_MAX_RETRY = 5
# 2026-08-06 태스커 2분 주기 도입 이후 3→5로 상향. 트레이딩 라이트(2분)와
# 스크래퍼(10분) 두 워크플로가 겹치는 창에서 order_history.json/trade_history_real.csv에
# 동시에 append하는 빈도가 늘어난다 — 재시도 예산이 부족하면 체결 기록이 조용히
# 누락된다(2026-07-08 수동청산 누락과 같은 계열).


def _token() -> str | None:
    return os.environ.get('GH_PAT') or os.environ.get('GITHUB_PAT') or os.environ.get('GITHUB_TOKEN')


def _headers(token: str) -> dict:
    return {'Authorization': f'token {token}', 'Accept': 'application/vnd.github.v3+json'}


def _url(path: str) -> str:
    return f'https://api.github.com/repos/{_OWNER}/{_REPO}/contents/{path}'


def fetch_text(path: str, log=print) -> tuple[str | None, str | None]:
    """(내용, sha). 파일이 없으면 ('', None). 조회 실패면 (None, None).

    '없음'과 '실패'를 가른다 — 실패를 빈 파일로 읽으면 기존 기록을 통째로
    날리는 쓰기가 나간다.
    """
    token = _token()
    if not token:
        log('[SecretStore] GH 토큰 없음 → 조회 불가')
        return None, None
    try:
        res = requests.get(f'{_url(path)}?ref={_BRANCH}', headers=_headers(token), timeout=_TIMEOUT)
        if res.status_code == 404:
            return '', None
        if res.status_code != 200:
            log(f'[SecretStore] {path} 조회 실패 HTTP {res.status_code}')
            return None, None
        payload = res.json()
        return base64.b64decode(payload['content']).decode('utf-8'), payload.get('sha')
    except Exception as e:
        log(f'[SecretStore] {path} 조회 예외: {e}')
        return None, None


def put_text(path: str, content: str, sha: str | None, message: str, log=print) -> bool:
    token = _token()
    if not token:
        return False
    body = {
        'message': message,
        'content': base64.b64encode(content.encode('utf-8')).decode('ascii'),
        'branch': _BRANCH,
    }
    if sha:
        body['sha'] = sha
    try:
        res = requests.put(_url(path), headers=_headers(token), json=body, timeout=_TIMEOUT)
        if res.status_code in (200, 201):
            return True
        if res.status_code in (409, 422):
            return False  # 충돌 — 호출부가 다시 읽어서 재시도한다
        log(f'[SecretStore] {path} 기록 실패 HTTP {res.status_code}')
        return False
    except Exception as e:
        log(f'[SecretStore] {path} 기록 예외: {e}')
        return False


def update_text(path: str, transform, message: str, log=print) -> bool:
    """읽기→변형→쓰기를 충돌 시 재시도한다 (read-modify-write).

    transform(현재내용: str) -> 새내용: str
    다른 런이 그 사이에 기록했으면 최신본을 다시 읽어 그 위에 얹는다 —
    덮어쓰지 않는 게 핵심이다.
    """
    for attempt in range(_MAX_RETRY):
        current, sha = fetch_text(path, log)
        if current is None:
            log(f'[SecretStore] {path} 조회 실패 — 기록을 건너뜁니다(덮어쓰지 않음)')
            return False
        if put_text(path, transform(current), sha, message, log):
            return True
        log(f'[SecretStore] {path} 충돌 — 최신본으로 재시도 ({attempt + 1}/{_MAX_RETRY})')
    log(f'[SecretStore] {path} 기록 실패: {_MAX_RETRY}회 충돌')
    return False


def append_json_list(path: str, record: dict, message: str, log=print,
                     newest_first: bool = True) -> bool:
    """JSON 배열 파일에 항목 하나를 덧붙인다."""
    def _t(current: str) -> str:
        try:
            items = json.loads(current) if current.strip() else []
        except Exception:
            log(f'[SecretStore] {path} 파싱 실패 — 기존 내용을 보존하고 중단')
            raise
        if not isinstance(items, list):
            items = []
        if newest_first:
            items.insert(0, record)
        else:
            items.append(record)
        return json.dumps(items, indent=2, ensure_ascii=False)

    try:
        return update_text(path, _t, message, log)
    except Exception:
        return False


def append_csv_row(path: str, row_line: str, header_line: str, message: str, log=print) -> bool:
    """CSV 파일 끝에 한 줄을 덧붙인다. 파일이 없으면 헤더부터 만든다."""
    def _t(current: str) -> str:
        if not current.strip():
            return f'﻿{header_line}\n{row_line}\n'
        base = current if current.endswith('\n') else current + '\n'
        return base + row_line + '\n'

    return update_text(path, _t, message, log)
