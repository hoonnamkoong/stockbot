"""KIS 확정 실현손익 조회 — '모른다'와 '매도가 없었다'를 가른다.

호출부(_sweep_stale_pending)가 둘을 **정반대로** 처리한다:
  - 모른다  → 원장을 손대지 않는다(추정치도 그대로, pending도 그대로).
  - 없었다  → 그 매도는 체결되지 않았다. 추정치를 통째로 되돌리고 포지션을 복원한다.

둘을 합치면 조회 한 번 실패했다고 팔지도 않은 손익을 확정하거나, 실제로 판
것을 미체결로 되돌린다. 어느 쪽이든 `effective_budget = budget + realized_pnl`
을 통해 다음 실주문 크기를 바꾼다.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.trade.realized_pnl import lookup_realized_pnl

CODE = '001210'
DATE = '2026-08-12T15:29:21'


def _rows(*rows):
    return lambda f, t, c: list(rows)


def _row(qty=34, amount=-12345.0, code=CODE, dt='20260812'):
    return {'pdno': code, 'trad_dt': dt, 'sll_qty': str(qty), 'rlzt_pfls': str(amount)}


def test_confirmed_profit_is_returned():
    ok, got = lookup_realized_pnl(CODE, DATE, request=_rows(_row()))

    assert ok is True
    assert got == {'qty': 34, 'amount': -12345.0}


def test_request_failure_is_not_a_zero():
    """조회 실패를 0으로 읽으면 '손익 0으로 청산했다'는 거짓이 된다."""
    ok, got = lookup_realized_pnl(CODE, DATE, request=lambda f, t, c: None)

    assert ok is False
    assert got is None


def test_no_rows_means_the_sell_never_filled():
    """조회는 됐는데 그 날 그 종목 매도가 없다 = 미체결. 확정된 사실이다."""
    ok, got = lookup_realized_pnl(CODE, DATE, request=_rows())

    assert ok is True
    assert got is None


def test_split_fills_are_summed():
    """분할 체결이면 같은 날 같은 종목이 여러 행으로 온다."""
    ok, got = lookup_realized_pnl(
        CODE, DATE, request=_rows(_row(qty=20, amount=-8000.0),
                                  _row(qty=14, amount=-4345.0)))

    assert ok is True
    assert got == {'qty': 34, 'amount': -12345.0}


def test_other_codes_and_dates_are_ignored():
    """계좌 전체 응답이 올 수 있다. 남의 손익을 이 종목에 붙이면 안 된다."""
    ok, got = lookup_realized_pnl(
        CODE, DATE, request=_rows(_row(code='005930', amount=999999.0),
                                  _row(dt='20260811', amount=888888.0),
                                  _row(qty=34, amount=-12345.0)))

    assert ok is True
    assert got == {'qty': 34, 'amount': -12345.0}


def test_unreadable_rows_are_a_failure_not_an_absence():
    """매도 행은 있는데 손익 필드를 못 읽었다. 이건 '매도 없음'이 아니다 —
    없음으로 읽으면 추정치를 되돌려 실제로 판 포지션을 되살린다."""
    bad = {'pdno': CODE, 'trad_dt': '20260812', 'sll_qty': '34', 'rlzt_pfls': None}
    ok, got = lookup_realized_pnl(CODE, DATE, request=_rows(bad))

    assert ok is False
    assert got is None


def test_bad_date_is_a_failure():
    ok, got = lookup_realized_pnl(CODE, '(없음)', request=_rows(_row()))

    assert ok is False
    assert got is None
