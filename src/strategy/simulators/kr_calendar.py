"""국내 심 공용 KST 거래일 유틸.

EOD 배치(쓰는 쪽)와 장중 루프(읽는 쪽)가 같은 날짜 키를 써야 한다. 배치가
`time.strftime('%Y%m%d')`로 **돌린 날**을 찍으면, 그 배치는 마감 뒤 16시에 도니
그 키가 맞는 장중 사이클이 존재하지 않는다 — 심11(미너비니)은 그 때문에
2026-08-20 배포 이래 매수가 구조적으로 0건이었다(2026-08-27 확인).

미국 심은 같은 고장을 us_calendar.watchlist_target_date()로 이미 고쳤다.
국내판도 같은 규약을 쓴다. 심을 추가할 때마다 복붙하지 말고 여기서 import한다.
"""
import datetime as dt

from src import market_calendar

_KST = dt.timezone(dt.timedelta(hours=9))

# 정규장 마감(KST). 이 시각을 지나야 "오늘 세션은 끝났다"고 본다.
_CLOSE_MIN = 15 * 60 + 30

# 다음 개장일을 찾을 때 훑을 최대 일수. 국내 최장 연휴(설·추석 + 주말 + 임시공휴일)를
# 넘겨야 한다. 달력이 이만큼도 못 채우면 주말 근사로 떨어진다.
_MAX_LOOKAHEAD = 14


def is_open(days: dict, yyyymmdd: str) -> bool:
    """개장 여부. 달력에 없으면 주말만 거르는 근사로 답한다.

    감시 목록 날짜는 주문 게이트가 아니라 서빙 키다. 판정 불가로 멈추면 그날치
    감시 목록이 통째로 사라지므로, 근사라도 키를 낸다 — 주문 경로의
    fail-closed(holiday-gate-kis-chk-holiday)와는 요구가 다르다.
    """
    verdict = market_calendar.lookup(days, yyyymmdd)
    if verdict is None:
        return dt.datetime.strptime(yyyymmdd, '%Y%m%d').weekday() < 5
    return verdict


def watchlist_target_date(now_kst: dt.datetime | None = None,
                          days: dict | None = None) -> str:
    """감시 목록이 서빙할 거래일 — **아직 안 끝난 가장 가까운 세션**.

    오늘 세션이 아직 안 끝났으면(개장 전이든 장중이든) 오늘, 이미 끝났거나
    휴장일이면 다음 개장일. 정규 EOD 배치(16:00 KST)는 마감 뒤라 다음 거래일을
    찍는다.

    장중에 만들어도 룩어헤드가 아니다 — 추세 템플릿·VCP·pivot은 전부 어제까지의
    확정 일봉으로 계산하고, 진입 판정은 장중 루프가 실시간가로 따로 한다
    (backtest-lookahead-trap).
    """
    now_kst = now_kst or dt.datetime.now(_KST)
    days = market_calendar.load_calendar() if days is None else days

    today = now_kst.date()
    mins = now_kst.hour * 60 + now_kst.minute
    if mins < _CLOSE_MIN and is_open(days, today.strftime('%Y%m%d')):
        return today.strftime('%Y%m%d')

    day = today
    for _ in range(_MAX_LOOKAHEAD):
        day += dt.timedelta(days=1)
        ymd = day.strftime('%Y%m%d')
        if is_open(days, ymd):
            return ymd
    # 달력이 연휴 길이를 못 넘길 만큼 낡았다. 주말 근사로 한 번 더 훑는다.
    day = today
    while True:
        day += dt.timedelta(days=1)
        if day.weekday() < 5:
            return day.strftime('%Y%m%d')
