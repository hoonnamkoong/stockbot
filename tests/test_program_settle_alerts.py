# -*- coding: utf-8 -*-
"""정산 결과를 사람에게 보낸다 — 로그와 배너만으로는 출근한 사람에게 닿지 않는다.

정산은 `realized_pnl`을 바꾸고 그게 곧 `effective_budget`, 즉 **다음 실주문 크기**다.
그런데 결과가 `print`로만 남았다. 확인하려면 GitHub Actions 로그를 열거나 대시보드를
봐야 하는데, 장 열리는 09:00에 사람이 거기 없을 수 있다.

이 레포에 이미 적힌 규칙이다: 돈 관련 경고는 `src/alerts.py`로 보낸다. 정산이
그 규칙에서 빠져 있었다.

- 성공은 쿨다운 없이 한 통. 정산되면 항목이 원장에서 사라지므로 다음 사이클엔
  미정산이 0건이고 알림도 없다 — 반복될 수 없는 사건이다.
- 실패는 **반드시 쿨다운**. 2분마다 재시도되므로 억제가 없으면 하루 195통이 된다.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.workers.program_trader import settle_and_notify

NOW = dt.datetime(2026, 11, 23, 9, 2)
BUDGET = 1000000


class _Spy:
    """alerts 모듈 대역."""

    def __init__(self):
        self.settled = []
        self.failed = []

    def notify_program_settled(self, count, before, after, budget, now, log=print):
        self.settled.append((count, before, after, budget))
        return True

    def notify_program_settle_failed(self, remaining, reasons, now, log=print):
        self.failed.append((remaining, list(reasons)))
        return True


def _ledger(rpnl=-100000.0, exits=None):
    led = {'realized_pnl': rpnl}
    if exits is not None:
        led['unreconciled_exits'] = exits
    return led


def test_정산되면_건수와_전후_금액과_주문기준이_간다():
    led = _ledger()
    spy = _Spy()

    def _settle(ledger, log=print, log_error=print, orders=None):
        ledger['realized_pnl'] = -300000.0
        ledger.pop('unreconciled_exits', None)
        return 5

    n = settle_and_notify(led, BUDGET, NOW, log=lambda *_: None,
                          log_error=lambda *_: None, settle=_settle, alerts_mod=spy)

    assert n == 5
    assert spy.failed == []
    (count, before, after, budget), = spy.settled
    assert count == 5
    assert before == -100000.0        # 사람이 전후를 대조할 수 있어야 한다
    assert after == -300000.0
    assert budget == BUDGET


def test_미정산이_없으면_조용하다():
    """평소 경로다. 여기서 한 통이라도 가면 알림이 쓸모없어진다."""
    spy = _Spy()
    n = settle_and_notify(_ledger(exits=None), BUDGET, NOW, log=lambda *_: None,
                          log_error=lambda *_: None,
                          settle=lambda ledger, log=print, log_error=print,
                                        orders=None: 0,
                          alerts_mod=spy)

    assert n == 0
    assert spy.settled == [] and spy.failed == []


def test_닫히지_않은_항목이_남으면_사유와_함께_알린다():
    led = _ledger(exits=[{'code': '000111'}, {'code': '000222'}])
    spy = _Spy()

    def _settle(ledger, log=print, log_error=print, orders=None):
        log_error('[Program] 000111 확정 실현손익 조회 실패(20261011~20261110)')
        log_error('[Program] 000222 수량이 맞는 매도를 특정하지 못했습니다')
        return 0

    n = settle_and_notify(led, BUDGET, NOW, log=lambda *_: None,
                          log_error=lambda *_: None, settle=_settle, alerts_mod=spy)

    assert n == 0
    assert spy.settled == []
    (remaining, reasons), = spy.failed
    assert remaining == 2
    assert any('조회 실패' in r for r in reasons)
    assert any('수량' in r for r in reasons)


def test_일부만_정산되면_둘_다_간다():
    """3건 닫고 2건 남은 상태를 '성공'으로만 알리면 남은 2건이 묻힌다."""
    led = _ledger(exits=[{'code': '000222'}, {'code': '000333'}])
    spy = _Spy()

    def _settle(ledger, log=print, log_error=print, orders=None):
        ledger['realized_pnl'] = -200000.0
        log_error('[Program] 000222 구간에 매도 기록이 없습니다')
        return 3

    settle_and_notify(led, BUDGET, NOW, log=lambda *_: None,
                      log_error=lambda *_: None, settle=_settle, alerts_mod=spy)

    assert len(spy.settled) == 1 and spy.settled[0][0] == 3
    assert len(spy.failed) == 1 and spy.failed[0][0] == 2


def test_정산이_터져도_매매를_멈추지_않는다():
    """알림이든 정산이든, 여기서 예외가 올라가면 주문 경로가 죽는다."""
    led = _ledger(exits=[{'code': '000111'}])
    errs = []

    def _boom(ledger, log=print, log_error=print, orders=None):
        raise RuntimeError('조회 폭발')

    class _AngrySpy(_Spy):
        def notify_program_settle_failed(self, remaining, reasons, now, log=print):
            raise RuntimeError('텔레그램 폭발')

    n = settle_and_notify(led, BUDGET, NOW, log=lambda *_: None,
                          log_error=errs.append, settle=_boom, alerts_mod=_AngrySpy())

    assert n == 0
    assert any('정산' in e for e in errs), f'실패를 로그에 남기지 않았다: {errs}'


def test_원장을_읽을_수_없어도_죽지_않는다():
    """realized_pnl이 숫자가 아니면(구 기록·손상) 알림 계산이 터질 수 있다."""
    led = {'realized_pnl': None, 'unreconciled_exits': [{'code': '000111'}]}
    spy = _Spy()
    n = settle_and_notify(led, BUDGET, NOW, log=lambda *_: None,
                          log_error=lambda *_: None,
                          settle=lambda ledger, log=print, log_error=print: 0,
                          alerts_mod=spy)
    assert n == 0
    assert len(spy.failed) == 1
