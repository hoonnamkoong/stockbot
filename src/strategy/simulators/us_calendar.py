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
