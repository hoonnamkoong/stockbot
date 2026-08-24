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
