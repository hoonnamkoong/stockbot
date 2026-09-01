# -*- coding: utf-8 -*-
"""국내·미국 세션 게이트.

태스커가 09:00~06:00 KST 2분 간격으로 **하나의** 트리거만 보낸다. 그 트리거를
국내장/미국장/둘 다 아님으로 가르는 게 이 모듈이다.

이 게이트가 없으면 밤새 실전 매매 루프가 돈다 — trade_loop.py는 휴장일만 보고
장중 시간은 안 본다(태스커가 09:00~15:30에만 불러줬으니 필요가 없었다).

**국내 게이트는 휴장일을 판정하지 않는다.** 요일과 시각만 본다. 휴장 판정은
trade_loop.py가 KIS chk-holiday로 fail-closed로 하며([[holiday-gate-kis-chk-holiday]]),
그 판정을 여기서 또 하면 라우팅 스텝이 KIS 호출에 묶이고 fail-closed가 두 곳으로
갈린다.
"""
import datetime as dt

from src.pipeline.context import PipelineContext
from src.session_gate import kr_session_open, us_session_open


def _kst(y, mo, d, h, mi):
    """PipelineContext.now_kst와 같은 naive KST."""
    return dt.datetime(y, mo, d, h, mi)


def _utc(y, mo, d, h, mi):
    return dt.datetime(y, mo, d, h, mi, tzinfo=dt.timezone.utc)


# ── 국내 ────────────────────────────────────────────────────────────
def test_kr_개장_경계():
    # 2026-08-27은 목요일
    assert kr_session_open(_kst(2026, 8, 27, 8, 59)) is False
    assert kr_session_open(_kst(2026, 8, 27, 9, 0)) is True


def test_kr_마감_경계():
    # 상한은 15:50이다(15:30이 아니다) — is_market_hours와 같은 창.
    assert kr_session_open(_kst(2026, 8, 27, 15, 49)) is True
    assert kr_session_open(_kst(2026, 8, 27, 15, 50)) is False


def test_kr_주말은_닫힌다():
    assert kr_session_open(_kst(2026, 8, 29, 10, 0)) is False  # 토
    assert kr_session_open(_kst(2026, 8, 30, 10, 0)) is False  # 일


def test_kr_밤에는_닫힌다():
    """태스커 창이 06:00까지 늘어난다 — 이 시각들이 열리면 실전 루프가 밤새 돈다."""
    for h, m in ((16, 0), (20, 0), (23, 0), (2, 0), (5, 59)):
        assert kr_session_open(_kst(2026, 8, 27, h, m)) is False, f'{h:02d}:{m:02d}'


def test_kr_게이트는_is_market_hours와_같은_창이다():
    """실거래 게이트(context.is_market_hours)와 라우터가 갈리면 안 된다.

    라우터가 넓으면 장 밖에서 실전 루프가 돌고, 좁으면 장중 사이클이 통째로
    사라진다. 두 구현이 따로 있으므로(무게 때문에 라우터는 stdlib 전용) 창을
    테스트로 묶는다.
    """
    ctx = PipelineContext.__new__(PipelineContext)   # __init__ 우회(시계·환경 안 읽음)
    ctx.is_trading_day = lambda: True
    for h in range(24):
        for m in (0, 29, 30, 49, 50, 59):
            now = _kst(2026, 8, 27, h, m)   # 목요일
            ctx.now_kst = now
            assert kr_session_open(now) == ctx.is_market_hours(), f'{h:02d}:{m:02d}'


# ── 미국 ────────────────────────────────────────────────────────────
def test_us_edt_경계():
    # EDT: 09:30~16:00 ET = 13:30~20:00 UTC
    assert us_session_open(_utc(2026, 8, 27, 13, 29)) is False
    assert us_session_open(_utc(2026, 8, 27, 13, 30)) is True
    assert us_session_open(_utc(2026, 8, 27, 19, 59)) is True
    assert us_session_open(_utc(2026, 8, 27, 20, 0)) is False


def test_us_est_경계():
    # EST(서머타임 종료 후): 09:30~16:00 ET = 14:30~21:00 UTC
    assert us_session_open(_utc(2026, 1, 15, 14, 29)) is False
    assert us_session_open(_utc(2026, 1, 15, 14, 30)) is True
    assert us_session_open(_utc(2026, 1, 15, 20, 59)) is True
    assert us_session_open(_utc(2026, 1, 15, 21, 0)) is False


def test_us_주말은_닫힌다():
    assert us_session_open(_utc(2026, 8, 29, 15, 0)) is False  # 토
    assert us_session_open(_utc(2026, 8, 30, 15, 0)) is False  # 일


# ── cron 지연을 피해 태스커로 옮긴 두 창 (2026-09-01) ────────────────
# us_eod_watchlist(22:00 UTC)·premarket_data(22:20 UTC)는 태스커 체인 밖의
# 네이티브 cron 전용이었다. 실측 지연이 +29분에서 +3~11시간으로 벌어졌고,
# 그 지연이 워치리스트 배치를 scraper 창 안으로 밀어 넣어 2026-09-01 사고가 났다.
#
# 두 cron 시각(07:00·07:20 KST)은 옛 태스커 창(09:00~06:00)의 사각지대였다.
# 창을 08:00까지 늘리면서 이 두 창이 그 안에 들어온다.

from src.session_gate import premarket_window, us_watchlist_window  # noqa: E402


def test_워치리스트_창은_미국_마감_뒤_아침에_열린다():
    # 화요일 07:00 KST = 월요일 22:00 UTC — 기존 cron과 같은 시각
    assert us_watchlist_window(_kst(2026, 9, 1, 7, 0)) is True
    assert us_watchlist_window(_kst(2026, 9, 1, 6, 59)) is False


def test_워치리스트_창은_오후까지_열려_있다():
    """07:00~08:00만 주면 1시간뿐이라 몇 시간짜리 장애를 못 버틴다 — EOD 창에서
    이미 겪은 실패다. 태스커가 09:00에 다시 열리므로 15:00까지 두면 재시도
    기회가 충분하고, 그래도 미국 개장(22:30 KST)보다 한참 이르다."""
    assert us_watchlist_window(_kst(2026, 9, 1, 14, 59)) is True
    assert us_watchlist_window(_kst(2026, 9, 1, 15, 0)) is False


def test_워치리스트_창은_토요일_아침까지_있다():
    """금요일 미국 마감(토 05:00~06:00 KST) 뒤에도 만들어야 다음 월요일 세션을
    잃지 않는다. 태스커 프로파일이 월~토인 이유와 같다."""
    assert us_watchlist_window(_kst(2026, 9, 5, 7, 0)) is True     # 토


def test_워치리스트_창은_월요일_아침에는_닫혀_있다():
    """월요일 07:00 KST = 일요일 22:00 UTC — 미국장이 없던 날의 다음 아침이다."""
    assert us_watchlist_window(_kst(2026, 8, 31, 7, 0)) is False   # 월
    assert us_watchlist_window(_kst(2026, 9, 6, 7, 0)) is False    # 일


def test_프리마켓_창은_국내_개장_전에_열린다():
    assert premarket_window(_kst(2026, 9, 1, 7, 20)) is True
    assert premarket_window(_kst(2026, 9, 1, 7, 19)) is False


def test_프리마켓_창은_개장_뒤에도_잠시_열려_있다():
    """개장 전이 이상적이지만, investor_flows.csv는 심13이 장중에 읽는다 —
    늦더라도 채우는 편이 빈 것보다 낫다."""
    assert premarket_window(_kst(2026, 9, 1, 11, 59)) is True
    assert premarket_window(_kst(2026, 9, 1, 12, 0)) is False


def test_프리마켓_창은_평일만():
    assert premarket_window(_kst(2026, 9, 5, 7, 30)) is False      # 토
    assert premarket_window(_kst(2026, 9, 6, 7, 30)) is False      # 일
