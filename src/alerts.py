"""장애 알림 — "봇이 뭔가 잘못했다"를 사람에게 보내는 유일한 경로.

리포트(notifier.py)와 다르다. 리포트는 PipelineContext.should_notify()의
정각(0~2분) 제한을 받지만, 여기는 받지 않는다. 장애는 정각에 나지 않는다.

왜 필요했나: 2026-08-08 점검에서, 실거래에서 가장 위험한 두 신호가 전부
표준출력에만 남는다는 게 드러났다.
  - program_trader의 "락을 빼앗겼습니다 — 중복 체결 가능성"
  - trade_executor의 "이 체결이 집계에서 누락될 수 있습니다"
둘 다 BaseWorker.log_error()를 썼는데 그건 print 한 줄이다. 실제 돈이 두 번
나갔을 수 있는 신호가 GitHub Actions 로그에만 남아 아무도 보지 않았다.
(2026-07-08에 179만원어치 청산이 집계에서 통째로 빠진 것도 같은 계열이다.)
"""

import json
import os
from datetime import datetime, timedelta

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
STATE_FILENAME = 'alert_dedup.json'


def _telegram_manager():
    """테스트가 갈아끼울 수 있도록 한 겹 둔다."""
    from src.telegram_manager import TelegramManager
    return TelegramManager()


def send_alert(text: str, log=print) -> bool:
    """장애 알림을 즉시 보낸다. 반복 억제 없음.

    발송 실패로 예외를 올리지 않는다 — 알림이 터져서 매매 경로가 죽으면
    원래 알리려던 문제보다 나빠진다. 대신 실패 자체를 로그에 남긴다: 알림이
    안 갔다는 사실까지 조용하면 "장애가 없었다"와 구분이 안 된다.
    """
    try:
        ok = bool(_telegram_manager().send_message(f"🚨 <b>StockBot 장애</b>\n\n{text}"))
        if not ok:
            log('[Alerts] 알림 발송에 실패했습니다: send_message가 False를 반환했습니다.')
        return ok
    except Exception as e:
        log(f'[Alerts] 알림 발송에 실패했습니다: {e}')
        return False


def send_alert_once(key: str, text: str, now: datetime, cooldown_min: int = 60,
                    data_dir: str | None = None, log=print) -> bool:
    """같은 key의 알림을 cooldown_min 안에서는 한 번만 보낸다.

    태스커가 2분 주기가 되면서 필요해졌다. 휴장 판정 실패처럼 하루 종일
    이어지는 장애는 매 트리거마다 울리면 하루 195건이 되고, 그러면 텔레그램
    rate limit에 걸리거나 사람이 둔감해진다 — 어느 쪽이든 알림이 없는 것과 같다.

    발송에 실패하면 기록하지 않는다. 못 보낸 알림을 '보냈다'로 적으면 쿨다운
    동안 장애가 통째로 묻힌다.
    """
    path = os.path.join(data_dir or DEFAULT_DATA_DIR, STATE_FILENAME)
    state = _load_state(path)

    last = state.get(key)
    if last:
        try:
            if now - datetime.fromisoformat(last) < timedelta(minutes=cooldown_min):
                log(f'[Alerts] {key} 알림 억제(쿨다운 {cooldown_min}분 이내)')
                return False
        except Exception:
            pass  # 파싱 불가한 기록은 '보낸 적 없다'로 본다 — 침묵보다 중복이 낫다

    if not send_alert(text, log):
        return False

    state[key] = now.isoformat()
    _save_state(path, state, log)
    return True


def _load_state(path: str) -> dict:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _save_state(path: str, state: dict, log=print) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception as e:
        log(f'[Alerts] 쿨다운 기록 실패(다음 사이클에 중복 발송될 수 있음): {e}')
