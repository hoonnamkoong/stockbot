# -*- coding: utf-8 -*-
"""신규 매수는 정규장이 닫히면(15:30) 멈춘다.

`is_market_hours()`의 상한은 15:50이고 그것이 `allow_buy`와 프로그램 매매 게이트를
겸했다. 그래서 15:30~15:49에 신규 매수가 나갈 수 있었다 — 태스커의 마지막 신호가
15:30이라 실제로 그 창에 런이 하나 떨어진다.

**왜 문제인가.** 15:20부터 동시호가이고 15:30에 정규장이 끝난다. 그 뒤에 낸 지정가는
정규장에서 체결될 수 없고, 브로커가 익일로 이월하면 **신호를 다시 확인하지 않은 채
익일 시가에 매수**가 된다 — 전략이 결정하지 않은 포지션이다.

**매도는 좁히지 않는다.** 매도는 리스크를 줄이는 행동이고, 안 채워지면 아무 일도
없으며 이월돼도 이미 나가려던 포지션을 정리한다.

매수 차단선은 `MARKET_CLOSE_HHMM` 하나에서 나온다 — 심(allow_buy)과 프로그램 매매가
서로 다른 시각을 쓰면 페이퍼 기록과 실전 동작이 갈린다([[program-trading-parity-mandate]]).
"""
import datetime

from src.pipeline.context import MARKET_CLOSE_HHMM
from src.pipeline.workers.program_trader import _buy_allowed


def _kst(h, m):
    return datetime.datetime(2026, 7, 30, h, m,
                             tzinfo=datetime.timezone(datetime.timedelta(hours=9)))


def test_차단선은_정규장_종료다():
    assert MARKET_CLOSE_HHMM == (15, 30)


def test_장중에는_매수가_허용된다():
    for h, m in ((9, 0), (10, 30), (14, 50), (15, 10), (15, 20)):
        assert _buy_allowed(_kst(h, m)) is True, f'{h:02d}:{m:02d}'


def test_정규장_종료_시각부터_매수가_막힌다():
    # 태스커의 마지막 신호가 정확히 15:30이다 — 경계 포함 여부가 실제로 걸린다.
    assert _buy_allowed(_kst(15, 30)) is False
    assert _buy_allowed(_kst(15, 35)) is False
    assert _buy_allowed(_kst(15, 49)) is False
    assert _buy_allowed(_kst(16, 10)) is False


def test_동시호가_구간은_아직_허용이다():
    # 15:20~15:30은 동시호가지만 정규장이다. 여기까지 좁히는 것은 별개 판단이라
    # 이번 변경 범위가 아니다 — 좁히려면 근거를 따로 세워야 한다.
    assert _buy_allowed(_kst(15, 25)) is True


def test_컨텍스트의_매수창과_같은_경계를_쓴다():
    from src.pipeline.context import PipelineContext
    ctx = PipelineContext.__new__(PipelineContext)
    ctx.is_trading_day = lambda: True
    for h, m, expected in ((9, 0, True), (15, 29, True), (15, 30, False), (15, 45, False)):
        ctx.now_kst = _kst(h, m)
        assert ctx.is_buy_window() is expected, f'{h:02d}:{m:02d}'


def test_거래일이_아니면_매수창이_닫힌다():
    from src.pipeline.context import PipelineContext
    ctx = PipelineContext.__new__(PipelineContext)
    ctx.now_kst = _kst(10, 0)
    for trading_day in (False, None):
        ctx.is_trading_day = lambda: trading_day
        assert ctx.is_buy_window() is False, '거래일인지 모르는 채로 매수하지 않는다'


def test_매도는_정규장_후에도_판단_대상이다():
    # is_market_hours()의 상한(15:50)은 그대로다 — 매수만 좁혔다는 것이 이 변경의 요점이다.
    from src.pipeline.context import PipelineContext
    ctx = PipelineContext.__new__(PipelineContext)
    ctx.is_trading_day = lambda: True
    ctx.now_kst = _kst(15, 40)
    assert ctx.is_market_hours() is True
    assert ctx.is_buy_window() is False
