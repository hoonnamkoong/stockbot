# -*- coding: utf-8 -*-
"""시각과 장 경계의 유일한 원천.

## 왜 생겼나 (2026-09-08 전수 실측)

KST가 **13개 파일에 각자** 정의돼 있었고(`_KST = dt.timezone(dt.timedelta(hours=9))`),
"지금 KST"를 구하는 방식이 다섯 갈래였다. 그중 둘은 naive를, 셋은 aware를 돌려줬다.
섞이면 비교에서 TypeError가 난다 — `session_gate.kr_session_open`이 "naive든
aware든 받는다"고 방어하고 있었던 것이 그 증거다.

장 경계는 더 나빴다. **같은 이름이 파일마다 다른 값**이었다:

    KR_CLOSE_HHMM = (15, 30)   src/data_freshness.py
    KR_CLOSE_HHMM = (15, 50)   src/session_gate.py

그리고 `session_gate.py`는 주석으로 동기화하고 있었다 — "상한이 15:50인 것은
context.is_market_hours와 맞춘 것이다". **주석은 실행되지 않는다.**

## 설계 규칙

이 모듈은 **아무것도 import 하지 않는다**(표준 라이브러리만). 라우팅 스텝이
pip install 앞에서 돌아야 하고, 시각 판정이 네트워크·설정·도메인에 묶이면
그 순간 다시 갈라진다.

경계 이름은 **뜻을 말한다.** `KR_CLOSE_HHMM`처럼 어느 마감인지 알 수 없는
이름이 값을 갈라놓았다.

재분열은 `tests/test_core_clock.py`의 가드 둘이 막는다 — 통합 자체가 아니라
그 가드가 본체다(토큰이 유일하게 재발 안 한 통합인 이유가 그것이다).
"""
import datetime as dt

__all__ = [
    'KST', 'now', 'now_naive', 'to_kst', 'as_naive', 'date_str', 'date_compact',
    'KR_OPEN', 'KR_REGULAR_CLOSE', 'KR_JUDGMENT_CLOSE',
]

KST = dt.timezone(dt.timedelta(hours=9))


# ── 시각 ────────────────────────────────────────────────────────────

def now() -> dt.datetime:
    """지금(KST, tz 붙음).

    `datetime.utcnow()`를 쓰지 않는다 — 폐기 예정이고 naive를 돌려준다.
    전수 실측에서 6곳이 그걸로 KST를 만들고 있었다.
    """
    return dt.datetime.now(KST)


def now_naive() -> dt.datetime:
    """지금(KST 벽시계, tz 없음).

    기존 `PipelineContext.now_kst` 관례가 naive라 그대로 남긴다. 한 번에 aware로
    바꾸면 그 값을 비교하는 자리마다 TypeError가 터진다 — 이관은 층별로 한다.
    """
    return dt.datetime.now(KST).replace(tzinfo=None)


def to_kst(value: dt.datetime) -> dt.datetime:
    """어떤 datetime이든 KST(tz 붙음)로 읽는다.

    **naive는 KST 벽시계로 본다.** 이 레포의 naive datetime은 전부 KST다
    (UTC로 읽으면 9시간이 밀린다).
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=KST)
    return value.astimezone(KST)


def as_naive(value: dt.datetime) -> dt.datetime:
    """KST 벽시계를 tz 없이. naive를 기대하는 옛 호출부에 넘길 때 쓴다."""
    return to_kst(value).replace(tzinfo=None)


def date_str(value: dt.datetime | dt.date | None = None) -> str:
    """`2026-09-08`. 값을 안 주면 오늘(KST)."""
    return _date_of(value).strftime('%Y-%m-%d')


def date_compact(value: dt.datetime | dt.date | None = None) -> str:
    """`20260908`. KIS 조회·상태 파일 키가 이 형식을 쓴다."""
    return _date_of(value).strftime('%Y%m%d')


def _date_of(value):
    if value is None:
        return now()
    return value


# ── 국내 장 경계 ────────────────────────────────────────────────────
#
# 셋은 서로 다른 뜻이고, 예전에는 이름이 그걸 말해주지 않았다.

KR_OPEN = (9, 0)

# 정규장 마감 = **신규 매수 차단선.** 이 시각 뒤에 낸 지정가는 정규장에서 체결될
# 수 없고, 브로커가 익일로 이월하면 신호를 다시 확인하지 않은 채 익일 시가에
# 사게 된다 — 전략이 결정하지 않은 포지션이다.
KR_REGULAR_CLOSE = (15, 30)

# 매도·기타 판단의 상한. 매수보다 20분 넓은 이유는 **청산은 리스크를 줄이는
# 행동**이라 좁힐 이유가 없기 때문이다. 여기를 낮추면 매도 판단이 일찍 끊긴다.
KR_JUDGMENT_CLOSE = (15, 50)
