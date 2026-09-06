# -*- coding: utf-8 -*-
"""매매 루프의 생존 신호 — "지금 살아 있나"를 분 단위로 잰다.

기존 감시(config/data_freshness.yaml)는 **세션 단위**다. 산출물이 거래일 하나를
건너뛰었는지를 보고, 감사기 자체도 하루 한두 번 돈다. 그래서 09:05에 루프가
멈추면 그 세션이 통째로 끝난 뒤에야 잡힌다.

여기서 재는 것은 다르다: **직전 한 바퀴가 언제 끝났나.** 세션 단위 감시와 겹치지
않고 보완한다 —
  - 신선도 감사: "어제 나와야 할 게 안 나왔다" (느리고 넓다)
  - 하트비트:    "지금 루프가 멈춰 있다"      (빠르고 좁다)

판정을 순수 함수로 빼 둔다. 루프와 알림 사이에 섞인 게이트는 아무도 테스트하지
않고, 그래서 도달 불가가 돼도 모른다 — 이 레포가 window_state와
should_reconnect에서 이미 두 번 겪었다.
"""
import datetime as dt

from src.session_gate import kr_session_open

_KST = dt.timezone(dt.timedelta(hours=9))

# 루프는 2분 격자로 돌고 한 런이 두 바퀴를 돈다. 15분이면 트리거를 일곱 번
# 놓친 것이라 정상 지터로 볼 수 없다. 더 좁혀도 발견이 빨라지지는 않는다 —
# 감시자(heartbeat_watch.yml)가 시간당 한 번 보기 때문이다.
MAX_AGE_MIN = 15

OK = 'ok'
STALE = 'stale'
OFF_SESSION = 'off_session'
UNKNOWN = 'unknown'


def _aware(t: dt.datetime | None) -> dt.datetime | None:
    """naive KST(PipelineContext.now_kst)와 tz 붙은 값을 함께 받는다."""
    if t is None or t.tzinfo is not None:
        return t
    return t.replace(tzinfo=_KST)


def last_success_at(runs: list[dict]) -> dt.datetime | None:
    """워크플로 런 목록에서 마지막으로 **완주한** 런의 완료 시각(KST). 없으면 None.

    상주 워커가 생기기 전까지 매매 루프의 생존 증거는 trading.yml의 런 이력이다.
    워커로 옮긴 뒤에는 beat_at의 출처만 바뀌고 judge()는 그대로 쓴다.

    성공한 런만 센다. 빨간 런은 "돌긴 돌았다"이지 "한 바퀴를 마쳤다"가 아니고,
    그걸 세면 루프가 매번 죽는데도 하트비트가 초록으로 보인다.
    """
    newest = None
    for run in runs or []:
        if run.get('conclusion') != 'success':
            continue
        try:
            ts = dt.datetime.fromisoformat(
                str(run.get('updated_at')).replace('Z', '+00:00')).astimezone(_KST)
        except (TypeError, ValueError):
            continue
        if newest is None or ts > newest:
            newest = ts
    return newest


def judge(now_kst: dt.datetime, beat_at: dt.datetime | None,
          trading_day: bool | None, max_age_min: int = MAX_AGE_MIN) -> str:
    """OK / STALE / OFF_SESSION / UNKNOWN 넷 중 하나.

    trading_day는 KIS 휴장 판정의 3값을 그대로 받는다(True/False/None).
    None을 STALE로 뭉개면 공휴일마다 거짓 경보가 나가고, OFF_SESSION으로
    뭉개면 달력이 낡은 동안 진짜 죽음을 놓친다. 그래서 네 번째 값으로 남긴다.
    """
    now_kst = _aware(now_kst)

    # 장 밖이면 달력을 몰라도 알릴 것이 없다 — 루프는 원래 안 돈다.
    if not kr_session_open(now_kst):
        return OFF_SESSION
    if trading_day is None:
        return UNKNOWN
    if not trading_day:
        return OFF_SESSION

    beat_at = _aware(beat_at)
    if beat_at is None:
        # 오늘 한 번도 안 뛴 경우다. '낡음'만 재면 이게 통째로 빠진다 —
        # 상주 워커에서는 이쪽이 가장 중요한 고장이다(아침에 아예 안 깸).
        return STALE
    return STALE if now_kst - beat_at > dt.timedelta(minutes=max_age_min) else OK
