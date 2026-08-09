"""장애 알림 — "봇이 뭔가 잘못했다"를 사람에게 보내는 유일한 경로.

리포트(notifier.py)와 다르다. 리포트는 발송 슬롯 게이트(src/report/gate.py —
11:00·14:00)의 제한을 받지만, 여기는 받지 않는다. 장애는 정해진 시각에 나지 않는다.

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


# 휴장 판정 실패 알림의 반복 억제 간격(분). 트리거가 2분이라 억제가 없으면
# 하루 195건이 된다. 장중(6.5시간)에 6~7번 울리는 셈이라 무시하기는 어렵다.
HOLIDAY_ALERT_COOLDOWN_MIN = 60


def notify_holiday_check_failed(today_display: str, now: datetime, log=print) -> bool:
    """거래일 판정 불가 — 봇이 통째로 멈춘다는 신호.

    **매매 경로와 스크래핑 경로가 같은 함수를 쓴다.** 2026-08-08 구조 변경으로
    스크래퍼는 trade_loop가 깨우는 종속 워크플로가 됐는데, 이 알림이 스크래퍼
    쪽에만 있었다 — 판정에 실패하면 trade_loop가 dispatch보다 앞에서 return하므로
    **정확히 그 시나리오에서 알림이 도달할 수 없었다.** 양쪽에 복사본을 두면
    문구가 갈리므로 여기 하나만 둔다.

    should_notify()의 정각 제한을 받지 않는다(모듈 docstring 참고) — 이건
    리포트가 아니라 "봇이 멈췄다"이고, 15/30/45분 런에서 침묵하면 장애를 놓친다.
    """
    return send_alert_once(
        'holiday_check_failed',
        f"<b>휴장 판정 실패</b>\n\n"
        f"{today_display} — 거래일 여부를 확인하지 못해 봇을 정지했습니다.\n"
        f"KIS chk-holiday 조회에 실패했습니다.\n"
        f"매매·스크래핑이 모두 멈춥니다(매매가 스크래퍼를 깨우는 구조).\n\n"
        f"수동 실행: trading.yml(실전 매매) / scraper.yml(스크래핑) → Run workflow\n"
        f"→ force_run 체크\n"
        f"⚠️ <b>먼저 오늘이 휴장일이 아님을 직접 확인한 뒤에만 사용하세요.</b>\n"
        f"이 옵션은 휴장일 게이트를 완전히 우회하며, 켜면 실매수 주문이 나갑니다.",
        now=now,
        cooldown_min=HOLIDAY_ALERT_COOLDOWN_MIN,
        log=log,
    )


def _load_state(path: str) -> dict:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


# 이 프로세스가 쿨다운 기록을 갱신했는가. 배포 목록이 이걸 보고 정한다.
_state_written = False


def state_was_written() -> bool:
    """이 런에서 쿨다운 기록이 바뀌었는가 — 즉 db-data에 올려야 하는가.

    쿨다운은 **다음 런에** 보여야 뜻이 있는데, 매 런이 새 컨테이너다. 안 올리면
    억제가 통째로 무력화되어 program_prep_over_budget(60분 쿨다운)이 2분마다
    나간다. 반대로 안 바뀐 파일을 매번 올리면, 그 사이 스크래퍼가 기록한 쿨다운을
    런 시작 시점 사본으로 되돌린다(lost update) — 두 워크플로는 concurrency
    그룹이 달라 실제로 동시에 돈다. 그래서 '바꾼 런만' 올린다.

    ⚠️ 이 파일은 **writer가 둘이다**(trading.yml·scraper.yml 양쪽이 알림을 낸다).
    scraper.yml은 `data/*.json`을 통째로 올리므로, 스크래퍼 배포(격자당 1회)가
    직전 trading 런의 기록을 런 시작 사본으로 되돌리는 창이 남아 있다. 정확히
    고치려면 배포가 cp가 아니라 키별 병합이어야 한다. 지금은 억제 간격이
    "2분마다"에서 "최대 10분마다"로 좁혀진 상태이고, 그보다 촘촘한 억제가
    필요해지면 그때 병합으로 간다.
    """
    return _state_written


def _save_state(path: str, state: dict, log=print) -> None:
    global _state_written
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)
        _state_written = True
    except Exception as e:
        log(f'[Alerts] 쿨다운 기록 실패(다음 사이클에 중복 발송될 수 있음): {e}')
