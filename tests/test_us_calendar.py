import datetime as dt

from src.strategy.simulators import us_calendar as c


def _utc(y, mo, d, h, mi=0):
    return dt.datetime(y, mo, d, h, mi, tzinfo=dt.timezone.utc)


# ── 워치리스트 날짜 키(쓰는 쪽 EOD 배치 ↔ 읽는 쪽 장중 루프) ──────────────
# 예전엔 양쪽 다 KST 날짜를 썼다. KST는 15:00 UTC에 날짜가 넘어가는데 그 시각이
# 미국 정규장 한복판이라, 장 시작 1시간 반 뒤부터 읽는 쪽이 존재하지 않는 다음날
# 파일을 찾아 유니버스가 통째로 비었다(월요일은 아예 하루 종일). 고정 UTC 시각을
# 주입해 그 경계를 직접 넘겨 본다.

def test_eod_stamp_and_intraday_read_match_across_kst_date_flip():
    """월요일 마감 배치가 찍은 키를, 화요일 장 종료 직전까지 읽어낸다."""
    assert c.next_us_trading_date(_utc(2026, 8, 24, 22)) == '20260825'
    assert c.us_trading_date(_utc(2026, 8, 25, 13, 30)) == '20260825'   # 09:30 ET 개장
    assert c.us_trading_date(_utc(2026, 8, 25, 19, 55)) == '20260825'   # 15:55 ET, KST는 이미 26일


def test_friday_eod_stamp_is_monday_and_monday_read_matches():
    """금요일 마감 배치는 월요일 키를 찍는다 — 주말 배치가 없으므로."""
    assert c.next_us_trading_date(_utc(2026, 8, 28, 22)) == '20260831'
    assert c.us_trading_date(_utc(2026, 8, 31, 14)) == '20260831'       # 10:00 ET 월요일


def test_date_key_holds_in_est_period():
    """EST(UTC-5) 구간도 동일 — 장 시간대가 14:30~21:00 UTC로 밀린다."""
    assert c.next_us_trading_date(_utc(2026, 1, 8, 22)) == '20260109'   # 목요일 마감 → 금요일
    assert c.us_trading_date(_utc(2026, 1, 9, 14, 30)) == '20260109'    # 09:30 EST 개장
    assert c.us_trading_date(_utc(2026, 1, 9, 20, 55)) == '20260109'    # 15:55 EST


# 2026-08-26 — next_us_trading_date는 **언제 돌리든 내일**을 찍는다. 그래서 장이
# 열려 있는 동안 배치를 돌려도 그 워치리스트를 오늘 못 쓴다. 고장을 고친 날 바로
# 검증할 수 없고 "내일 확인"이 반복됐다(그 다음 날 또 다른 게 걸리면 무한히 밀린다).
# 워치리스트가 서빙해야 할 날짜는 "아직 안 끝난 가장 가까운 세션"이다.

def test_target_date_is_today_during_session():
    """장중에 돌리면 오늘치 — 그 자리에서 쓸 수 있어야 한다."""
    assert c.watchlist_target_date(_utc(2026, 8, 26, 15, 16)) == '20260826'  # 11:16 EDT


def test_target_date_is_today_before_open():
    """개장 전에 돌려도 오늘치 — 오늘 세션이 아직 안 끝났다."""
    assert c.watchlist_target_date(_utc(2026, 8, 26, 12)) == '20260826'  # 08:00 EDT


def test_target_date_is_next_day_after_close():
    """정규 야간 배치(22:00 UTC = 18:00 EDT)는 지금까지처럼 다음 거래일."""
    assert c.watchlist_target_date(_utc(2026, 8, 26, 22)) == '20260827'


def test_target_date_friday_after_close_is_monday():
    assert c.watchlist_target_date(_utc(2026, 8, 28, 22)) == '20260831'


def test_target_date_on_weekend_is_monday():
    """토요일 낮은 '오늘 세션'이 없다 — 다음 거래일로 넘어가야 한다."""
    assert c.watchlist_target_date(_utc(2026, 8, 29, 15)) == '20260831'  # 토 11:00 EDT
    assert c.watchlist_target_date(_utc(2026, 8, 30, 15)) == '20260831'  # 일 11:00 EDT


def test_target_date_matches_intraday_reader_during_session():
    """쓰는 쪽과 읽는 쪽이 같은 키여야 한다 — 이 모듈이 존재하는 이유."""
    now = _utc(2026, 8, 26, 15, 16)
    assert c.watchlist_target_date(now) == c.us_trading_date(now)
