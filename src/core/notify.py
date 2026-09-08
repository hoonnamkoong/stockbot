# -*- coding: utf-8 -*-
"""텔레그램으로 나가는 유일한 길.

## 왜 생겼나 (2026-09-08 실측)

발신자가 셋이었고 **기능이 서로 달랐다:**

    src/telegram_manager.py             requests   분할 O  재시도 O
    scripts/notify_workflow_failure.py  urllib     분할 X  재시도 X
    scripts/audit_data_freshness.py     urllib     분할 X  재시도 X

sendMessage 상한은 4096자이고 **넘으면 API가 그냥 거부한다.** 분할이 한 곳에만
있었으므로 실패 알림과 신선도 감사 보고는 길어지면 통째로 사라졌다 — 하필 그 둘이
"뭔가 잘못됐다"를 알리는 경로이고, 길어질 때는 대개 문제가 많을 때다.

## 왜 표준 라이브러리인가

urllib 쪽 둘은 실수가 아니었다. 두 파일 모두 **"실패 지점이 pip install일 수도
있다"**를 근거로 표준 라이브러리만 썼다. 코어가 `requests`를 요구하면 그 성질이
깨진다 — 거꾸로 코어가 표준 라이브러리면 셋이 모이면서 분할·재시도를 나머지 둘도
갖는다. 잃는 것 없이 얻는 쪽이다.

## 여기 없는 것

**쿨다운은 여기 두지 않는다.** 같은 장애로 2분마다 울리지 않게 하는 것은 정책이고,
그건 `src/alerts.py`가 상태 파일과 함께 갖는다. 이 모듈은 "보낸다/못 보냈다"만
안다 — 그래야 리포트(쿨다운 없음)와 장애 알림(쿨다운 있음)이 같은 길을 쓴다.

재분열은 `tests/test_core_notify.py`의 마지막 가드가 막는다.
"""
import os
from urllib import error, parse, request

__all__ = ['send', 'split_chunks', 'SAFE_LEN']

_API = 'https://api.telegram.org/bot{token}/sendMessage'

# 실제 상한은 4096자. HTML 태그·이모지의 바이트 오차를 감안해 여유를 둔다.
# (2026-08-11: 딥다이브가 2→5종목으로 늘며 한 메시지가 상한을 넘었고,
#  당시 코드는 그 거부를 아무도 안 보고 '발송 완료'로 기록했다.)
SAFE_LEN = 3900

_TIMEOUT_SEC = 15


def split_chunks(text: str, limit: int = SAFE_LEN) -> list[str]:
    """빈 줄(문단) 경계로 나눠 각 조각이 limit 이하가 되게 묶는다.

    문단 하나가 그 자체로 limit을 넘는 드문 경우만 강제로 자른다.
    순수 함수라 경계 동작을 테스트가 직접 고정한다.
    """
    chunks: list[str] = []
    current = ''
    for para in text.split('\n\n'):
        candidate = f'{current}\n\n{para}' if current else para
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ''
        if len(para) > limit:
            for start in range(0, len(para), limit):
                chunks.append(para[start:start + limit])
        else:
            current = para
    if current:
        chunks.append(current)
    return chunks


def _post(url: str, data: dict, timeout: int) -> bool:
    """한 번 보낸다. HTTP 오류는 예외로 올라온다(urlopen이 4xx/5xx에 raise)."""
    body = parse.urlencode(data).encode()
    with request.urlopen(request.Request(url, data=body, method='POST'),
                         timeout=timeout):
        return True


def send(text: str, *, parse_mode: str | None = 'HTML',
         token: str | None = None, chat_id: str | None = None,
         log=print) -> bool:
    """텔레그램으로 보낸다. 상한을 넘으면 나눠서 순차 발송.

    **하나라도 실패하면 False.** 일부만 갔는데 성공으로 기록되면 나머지가
    조용히 사라진다.

    **예외를 올리지 않는다.** 알림이 터져서 매매 경로가 죽으면 원래 알리려던
    문제보다 나빠진다. 대신 실패 자체를 로그에 남긴다 — 안 갔다는 사실까지
    조용하면 '장애가 없었다'와 구분되지 않는다.
    """
    token = token or os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = chat_id or os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        log('[Notify] 텔레그램 시크릿 없음 — 발송 생략')
        return False

    url = _API.format(token=token)
    ok = True
    chunks = split_chunks(text)
    if len(chunks) > 1:
        log(f'[Notify] 메시지가 {len(text)}자라 {len(chunks)}개로 나눠 보냅니다.')

    for chunk in chunks:
        if not _send_one(url, chunk, parse_mode, log):
            ok = False
    return ok


def _send_one(url: str, text: str, parse_mode: str | None, log) -> bool:
    """실패하면 서식을 빼고 한 번 더. LLM 요약에 <, >가 섞여 HTML 파싱이
    깨지는 일이 실제로 있었다 — 그때 메시지를 통째로 잃는 것보다 낫다."""
    data = {'chat_id': _chat_id_of(url), 'text': text}
    if parse_mode:
        data['parse_mode'] = parse_mode
    try:
        return _post(url, data, _TIMEOUT_SEC)
    except (error.URLError, OSError) as e:
        log(f'[Notify] 발송 실패: {e}')
    except Exception as e:                      # noqa: BLE001 - 알림은 절대 안 죽는다
        log(f'[Notify] 발송 실패(예상 밖): {e}')

    if not parse_mode:
        return False
    log('[Notify] 서식 없이 재시도합니다.')
    try:
        return _post(url, {'chat_id': data['chat_id'], 'text': text}, _TIMEOUT_SEC)
    except Exception as e:                      # noqa: BLE001
        log(f'[Notify] 재시도도 실패: {e}')
        return False


# chat_id는 URL이 아니라 본문으로 간다. _post를 갈아끼우는 테스트가
# 본문만 보면 되도록, 조회는 이 한 줄로 모아 둔다.
def _chat_id_of(_url: str) -> str:
    return os.environ.get('TELEGRAM_CHAT_ID', '').strip()
