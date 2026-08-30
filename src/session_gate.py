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


def us_session_open(now_utc: dt.datetime | None = None) -> bool:
    """평일 09:30~16:00 ET인가. zoneinfo가 서머타임을 자동 반영한다."""
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    local = now_utc.astimezone(_NY)
    if local.weekday() >= 5:  # 토(5)·일(6)
        return False
    return US_OPEN_HHMM <= (local.hour, local.minute) < US_CLOSE_HHMM
