"""국내 EOD 워치리스트 날짜 키 — 쓰는 쪽(EOD 배치) ↔ 읽는 쪽(장중 루프).

2026-08-27 진단: scripts/run_eod_sims.py가 심11 감시 목록을 `time.strftime('%Y%m%d')`
= **배치를 돌린 날**로 찍었는데, 장중 로더(sim11_minervini.get_universe)는
**오늘** 날짜로만 읽는다(fail-closed). 배치는 마감 뒤 16시에 도니 그 키가 맞는
장중 사이클이 존재하지 않는다 — 심11은 08-20 배포 이래 매수가 구조적으로 0건이었다.

미국 심은 같은 고장을 커밋 #57에서 watchlist_target_date()로 이미 고쳤다
(src/strategy/simulators/us_calendar.py). 국내판에도 같은 규약을 둔다:
**아직 안 끝난 가장 가까운 세션**.
"""
import datetime as dt

from src.strategy.simulators import kr_calendar as c

# KIS chk-holiday가 주는 형태({YYYYMMDD: 'Y'|'N'}). 2026-08-27은 목요일.
_DAYS = {
    '20260827': 'Y',  # 목
    '20260828': 'Y',  # 금
    '20260829': 'N',  # 토
    '20260830': 'N',  # 일
    '20260831': 'Y',  # 월
}


def _kst(y, mo, d, h, mi=0):
    return dt.datetime(y, mo, d, h, mi, tzinfo=dt.timezone(dt.timedelta(hours=9)))


def test_target_date_is_today_during_session():
    """장중에 돌리면 오늘치 — 그 자리에서 쓸 수 있어야 한다(당일 검증 가능)."""
    assert c.watchlist_target_date(_kst(2026, 8, 27, 11), _DAYS) == '20260827'


def test_target_date_is_today_before_open():
    """개장 전에 돌려도 오늘치 — 오늘 세션이 아직 안 끝났다."""
    assert c.watchlist_target_date(_kst(2026, 8, 27, 8), _DAYS) == '20260827'


def test_eod_batch_after_close_stamps_next_trading_day():
    """정규 EOD 배치(16:00 KST)는 마감 뒤라 다음 거래일을 찍는다.

    이게 이 수정의 본체다 — 예전엔 여기서 '오늘'을 찍어 아무도 못 읽었다.
    """
    assert c.watchlist_target_date(_kst(2026, 8, 27, 16), _DAYS) == '20260828'


def test_close_boundary_is_1530():
    """15:30 정각은 이미 마감 — 그 가격으로는 못 산다."""
    assert c.watchlist_target_date(_kst(2026, 8, 27, 15, 29), _DAYS) == '20260827'
    assert c.watchlist_target_date(_kst(2026, 8, 27, 15, 30), _DAYS) == '20260828'


def test_friday_close_skips_weekend():
    """금요일 마감 배치는 월요일을 찍는다 — 주말엔 배치가 없다."""
    assert c.watchlist_target_date(_kst(2026, 8, 28, 16), _DAYS) == '20260831'


def test_holiday_is_skipped_by_calendar():
    """달력이 휴장(N)이라 한 날은 건너뛴다. 국내는 연휴가 잦다."""
    days = dict(_DAYS, **{'20260828': 'N'})  # 금요일 임시공휴일
    assert c.watchlist_target_date(_kst(2026, 8, 27, 16), days) == '20260831'


def test_run_on_holiday_targets_next_open_day():
    """휴장일에 돌리면 시각과 무관하게 다음 개장일 — 오늘은 세션이 없다."""
    assert c.watchlist_target_date(_kst(2026, 8, 29, 11), _DAYS) == '20260831'


def test_falls_back_to_weekday_when_calendar_missing():
    """달력이 비면 주말만 거른다(미국 경로와 같은 근사).

    감시 목록 날짜는 주문 게이트가 아니라 서빙 키다 — 판정 불가로 멈추면
    그날치가 통째로 사라지므로, 근사라도 키를 낸다.
    """
    assert c.watchlist_target_date(_kst(2026, 8, 28, 16), {}) == '20260831'
    assert c.watchlist_target_date(_kst(2026, 8, 27, 11), {}) == '20260827'
