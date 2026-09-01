# -*- coding: utf-8 -*-
"""국내·미국 세션 게이트 — 하나의 태스커 트리거를 두 시장으로 가른다.

태스커는 09:00~06:00 KST에 2분 간격으로 trading.yml 하나만 부른다. 미국 심을
GitHub 네이티브 cron으로 돌리던 방식이 2026-08-27부터 통째로 죽었기 때문이다
(발화 수 18 → 1 → 0/일, 남은 런도 폐장 뒤라 즉시 종료 — 목·금 세션 거래 0건).
실패가 아니라 **미발화**라 Actions에 빨간 X조차 안 남았다.

이 모듈은 표준 라이브러리만 쓴다. 라우팅 스텝이 pip install 앞에서 돌아야
장 밖 트리거(하루 200건 남짓)가 checkout만 하고 20초에 끝나기 때문이다.

**휴장일은 판정하지 않는다.** 요일과 시각만 본다. 국내 휴장 판정은 trade_loop.py가
KIS chk-holiday로 fail-closed로 하고, 여기서 또 하면 라우팅이 KIS 호출에 묶이며
fail-closed 지점이 둘로 갈린다.
"""
import datetime as dt
from zoneinfo import ZoneInfo

_NY = ZoneInfo('America/New_York')
_KST = dt.timezone(dt.timedelta(hours=9))

# 국내 창. 상한이 15:50인 것은 src.pipeline.context.is_market_hours와 맞춘 것이다
# — 매도·기타 판단이 마감(15:30) 직후까지 이어진다. 신규 매수 차단선(15:30)은
# 별개이며 program_trader가 MARKET_CLOSE_HHMM로 따로 건다.
KR_OPEN_HHMM = (9, 0)
KR_CLOSE_HHMM = (15, 50)

# 산출물 신선도 감사를 돌리는 창 — "어젯밤 뭐가 안 돌았나"를 하루 한 번 받는다.
#
# 개장 **전**(08:30)에 두고 싶었지만 태스커 창이 09:00부터라 그 시각엔 트리거가
# 없다(tests/test_session_router.py의 창 검사가 이걸 잡았다). 개장 직후로 둔다 —
# 감사는 알려줄 뿐 고쳐주지 않으므로, 사람이 세션 중에 대응할 시간이면 충분하다.
KR_AUDIT_OPEN_HHMM = (9, 0)
KR_AUDIT_CLOSE_HHMM = (9, 30)

# 장 마감 뒤 EOD 배치를 깨우는 창. 태스커가 2분마다 때리므로 넓을 필요는 없지만,
# 트리거 몇 개가 유실돼도 하루 한 번은 걸리도록 1시간을 준다. 실제 중복 방지는
# scripts/dispatch_eod_data.py의 '오늘 마감 뒤 런이 있나'가 한다.
KR_EOD_OPEN_HHMM = (16, 0)
# 2026-09-01: 17:00 → 23:00. 그날 16:00 EOD가 KIS 연결 타임아웃으로 죽었고,
# 재시도도 같은 이유로 죽었다. 창이 1시간뿐이라 **몇 시간짜리 외부 장애를 못
# 버틴다** — 그 한 시간을 놓치면 심9-1·심11이 다음 세션을 통째로 잃는다.
#
# 늦게 도는 것은 무해하다: eod_data.yml 자체가 장중(UTC < 06:30)이면 수집을
# 건너뛰는 게이트를 갖고 있고, 태스커 창은 06:00 KST까지 열려 있다. 23:00까지면
# 다음 09:00보다 열 시간 앞선다.
KR_EOD_CLOSE_HHMM = (23, 0)

# 미국 정규장. zoneinfo가 서머타임을 자동 반영하므로 ET로 적는다.
US_OPEN_HHMM = (9, 30)
US_CLOSE_HHMM = (16, 0)


def kr_session_open(now_kst: dt.datetime | None = None) -> bool:
    """평일 09:00~15:50 KST인가. now_kst는 naive KST(=PipelineContext.now_kst)든
    tz가 붙은 값이든 받는다."""
    if now_kst is None:
        now_kst = dt.datetime.now(_KST).replace(tzinfo=None)
    if now_kst.weekday() >= 5:
        return False
    return KR_OPEN_HHMM <= (now_kst.hour, now_kst.minute) < KR_CLOSE_HHMM


def kr_audit_window(now_kst: dt.datetime | None = None) -> bool:
    """평일 08:30~09:00 KST인가 — 개장 전 신선도 감사 창."""
    if now_kst is None:
        now_kst = dt.datetime.now(_KST).replace(tzinfo=None)
    if now_kst.weekday() >= 5:
        return False
    return KR_AUDIT_OPEN_HHMM <= (now_kst.hour, now_kst.minute) < KR_AUDIT_CLOSE_HHMM


def kr_eod_window(now_kst: dt.datetime | None = None) -> bool:
    """평일 16:00~23:00 KST인가 — 장 마감 뒤 EOD 배치를 깨우는 창.

    창 안에서 매 트리거(2분)마다 판정하지만 실제 dispatch는
    scripts/dispatch_eod_data.py가 정한다 — 성공했으면 생략, 돌고 있으면 생략,
    실패했으면 간격을 두고 재시도, 상한에 닿으면 사람을 부른다.
    """
    if now_kst is None:
        now_kst = dt.datetime.now(_KST).replace(tzinfo=None)
    if now_kst.weekday() >= 5:
        return False
    return KR_EOD_OPEN_HHMM <= (now_kst.hour, now_kst.minute) < KR_EOD_CLOSE_HHMM


def us_session_open(now_utc: dt.datetime | None = None) -> bool:
    """평일 09:30~16:00 ET인가. zoneinfo가 서머타임을 자동 반영한다."""
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    local = now_utc.astimezone(_NY)
    if local.weekday() >= 5:  # 토(5)·일(6)
        return False
    return US_OPEN_HHMM <= (local.hour, local.minute) < US_CLOSE_HHMM
