"""US 심 공용 ET 거래일 유틸.

EOD 배치(쓰는 쪽)와 장중 루프(읽는 쪽)가 같은 날짜 키를 써야 한다. KST 기준으로
계산하면 15:00 UTC에 날짜가 넘어가는데 그 시각이 미국 정규장 한복판이라, 장 시작
1시간 반 뒤부터 읽는 쪽이 존재하지 않는 다음날 파일을 찾아 유니버스가 통째로 빈다
(2026-08-23, 커밋 `7b6dc7245`). 심마다 복붙하면 같은 버그를 다시 심을 위험이 있어
공용 모듈로 뺀다 — US 심을 추가할 때마다 여기서 import한다.
"""
import datetime as dt
from zoneinfo import ZoneInfo

_NY = ZoneInfo('America/New_York')


def us_trading_date(now_utc: dt.datetime | None = None) -> str:
    """읽기 시점의 미국 거래일(ET 캘린더 날짜, YYYYMMDD). 장중 루프가
    is_us_market_open()으로 게이트한 뒤 호출하므로 항상 평일이다."""
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    return now_utc.astimezone(_NY).strftime('%Y%m%d')


def next_us_trading_date(now_utc: dt.datetime | None = None) -> str:
    """EOD 배치가 저장할 날짜 키 — '오늘 마감 기준으로 계산한, 다음 거래일'
    (ET 기준, 주말은 건너뛴다). 금요일 마감 배치는 월요일 날짜를 찍는다."""
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    local = now_utc.astimezone(_NY) + dt.timedelta(days=1)
    while local.weekday() >= 5:  # 토(5)·일(6)
        local += dt.timedelta(days=1)
    return local.strftime('%Y%m%d')


# 정규장 마감(ET). 이 시각을 지나야 "오늘 세션은 끝났다"고 본다.
_CLOSE_HOUR = 16


def watchlist_target_date(now_utc: dt.datetime | None = None) -> str:
    """워치리스트가 서빙할 거래일 — **아직 안 끝난 가장 가까운 세션**.

    오늘 세션이 아직 안 끝났으면(개장 전이든 장중이든) 오늘, 이미 끝났거나
    주말이면 다음 거래일. 정규 야간 배치(22:00 UTC = 18:00 ET)는 마감 뒤라
    지금까지처럼 다음 거래일을 찍는다 — 그 경로의 동작은 그대로다.

    next_us_trading_date는 **언제 돌리든 내일**을 찍는다. 그래서 장이 열려 있는
    동안 배치를 돌려도 그 워치리스트를 오늘 쓸 수 없었고, 고장을 고친 날 바로
    검증하지 못해 "내일 확인"이 반복됐다(그 다음 날 또 다른 게 걸리면 무한히
    밀린다). 배치를 언제 돌리든 가장 가까운 세션에 쓰이게 하는 게 이 함수다.

    장중에 만들어도 룩어헤드가 아니다 — 채널·피봇·ATR·평균거래대금은 전부
    `daily_closes`(오늘 봉 제외, 어제까지 확정치)로 계산한다. 어젯밤 배치가
    만들었을 값과 같다. 현재가만 판정 시점 관측값으로 더 신선하게 들어간다.
    """
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    local = now_utc.astimezone(_NY)
    if local.weekday() < 5 and local.hour < _CLOSE_HOUR:
        return local.strftime('%Y%m%d')
    return next_us_trading_date(now_utc)
