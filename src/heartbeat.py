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

from src.session_gate import kr_session_open, KR_CLOSE_HHMM, KR_OPEN_HHMM
from src.core import clock

_KST = clock.KST
# 루프는 2분 격자로 돌고 한 런이 두 바퀴를 돈다. 15분이면 트리거를 일곱 번
# 놓친 것이라 정상 지터로 볼 수 없다. 더 좁혀도 발견이 빨라지지는 않는다 —
# 감시자(heartbeat_watch.yml)가 30분 격자로 보기 때문이다(2026-09-16에 시간당
# 1회 → 30분으로 좁혔다. 그 격자는 알림 통수와 직결돼 있어
# scripts/check_heartbeat.py 독스트링의 쿨다운 주의를 같이 읽을 것).
# ⚠ 이 값은 감시자 발화의 **하한**도 정한다 — KR_OPEN + MAX_AGE_MIN 이전에
# 깨우면 아침 첫 완주가 아직 임계 안에 없어 정상인 날에도 stale이 뜬다.
MAX_AGE_MIN = 15

OK = 'ok'
STALE = 'stale'
OFF_SESSION = 'off_session'
UNKNOWN = 'unknown'
# 장 밖인데 **지난 세션을 통째로 빼먹었다.** STALE과 섞지 않는다 — 조치가 다르고
# (지금 깨우기 vs 어제부터 죽어 있었다) 발화 빈도도 다르다.
SESSION_MISSED = 'session_missed'


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


def last_closed_session(now_kst: dt.datetime, days: dict,
                        max_lookback: int = 14) -> str | None:
    """지금 기준으로 **이미 끝난** 가장 최근 거래 세션(YYYYMMDD). 모르면 None.

    달력(`data/market_calendar.json`의 days)을 뒤로 훑는다. 구멍을 만나면 즉시
    None — 모르는 채로 "세션을 빼먹었다"고 알리면 공휴일마다 거짓 경보가 난다.
    주말은 달력을 안 봐도 장이 없으므로 건너뛴다(달력이 부분 저장돼 있어도
    주말 때문에 눈이 멀지 않게).

    `market_calendar.lookup`을 쓰지 않고 여기서 읽는다. 그 모듈은 최상단에서
    requests를 import해서, 끌어오면 requests 없는 워크플로 스텝이 같이 죽는다
    (2026-09-09 토큰 갱신이 정확히 그렇게 죽었다).
    """
    now_kst = _aware(now_kst)
    day = now_kst.date()
    # 오늘 세션이 아직 안 끝났으면 오늘은 후보가 아니다. 마감 정각은 끝난 것으로 센다.
    if (now_kst.hour, now_kst.minute) < KR_CLOSE_HHMM:
        day -= dt.timedelta(days=1)

    for _ in range(max_lookback):
        if day.weekday() < 5:
            state = (days or {}).get(day.strftime('%Y%m%d'))
            if state not in ('Y', 'N'):
                return None
            if state == 'Y':
                return day.strftime('%Y%m%d')
        day -= dt.timedelta(days=1)
    return None


def _ran_in_session(beat_at: dt.datetime | None, session: str) -> bool:
    """그 세션 개장 이후에 완주가 있었나.

    세션 **안**이 아니라 개장 **이후**로 재는 이유: beat_at은 가장 최근 완주
    하나뿐이라 "세션 안에 하나라도 있었나"를 물을 수 없다. 개장 이후면
    적어도 그 세션이 통째로 비지는 않았다. 세션 일부만 죽은 경우는 여기서
    못 잡고 STALE의 몫으로 남는다 — 두 질문을 한 함수에 섞지 않는다.
    """
    if beat_at is None:
        return False
    try:
        opened = dt.datetime.strptime(session, '%Y%m%d').replace(
            hour=KR_OPEN_HHMM[0], minute=KR_OPEN_HHMM[1], tzinfo=_KST)
    except (TypeError, ValueError):
        return True          # 못 읽으면 판정하지 않는다(침묵 쪽으로)
    return _aware(beat_at) >= opened


def judge(now_kst: dt.datetime, beat_at: dt.datetime | None,
          trading_day: bool | None, max_age_min: int = MAX_AGE_MIN,
          last_session: str | None = None) -> str:
    """OK / STALE / SESSION_MISSED / OFF_SESSION / UNKNOWN 다섯 중 하나.

    trading_day는 KIS 휴장 판정의 3값을 그대로 받는다(True/False/None).
    None을 STALE로 뭉개면 공휴일마다 거짓 경보가 나가고, OFF_SESSION으로
    뭉개면 달력이 낡은 동안 진짜 죽음을 놓친다. 그래서 네 번째 값으로 남긴다.
    """
    now_kst = _aware(now_kst)

    # 장 밖이면 "지금 멎었나"는 물을 수 없다 — 루프는 원래 안 돈다. 하지만
    # "지난 세션을 돌았나"는 물을 수 있고, 그 둘은 다른 질문이다. 예전에는
    # 여기서 바로 반환해 2026-11-06에 `마지막완주 33시간 전`을 찍고도
    # 침묵했다(태스커 정지로 금·월 두 세션 상실).
    if not kr_session_open(now_kst):
        if last_session and not _ran_in_session(beat_at, last_session):
            return SESSION_MISSED
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
