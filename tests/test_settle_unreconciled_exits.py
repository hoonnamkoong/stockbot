# -*- coding: utf-8 -*-
"""수동 청산분 정산 — 쌓아두기만 하던 `unreconciled_exits`를 KIS 확정값으로 닫는다.

보유분을 손으로 시장가 매도하면 체결가가 `price: 0`으로 기록되는 경로라
(history.json) 우리 기록만으로는 손익을 영원히 못 낸다. 그런데 한투에는
있다 — TTTC8715R이 종목·매매일별 확정 실현손익을 준다.

빠져 있던 것은 조회 능력이 아니라 **연결**이었다. `_sweep_stale_pending`은 이미
같은 조회를 쓰는데 `unreconciled_exits`만 그 경로를 안 탔고, 한번 쌓인 항목을
지우는 코드가 아예 없어 배너가 영구히 남았다.

정산값은 `realized_pnl`에 들어간다 — 표시용이 아니라
`effective_budget = budget + realized_pnl`로 **다음 실주문 크기**가 된다.
그래서 모르면 건드리지 않는다.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.workers.program_trader import settle_unreconciled_exits


def _exit(code='000111', qty=50, cost=500000.0, date='2026-01-07', since=None):
    e = {'date': date, 'code': code, 'name': code, 'quantity': qty,
         'avg_price': cost / qty, 'cost_basis': cost}
    if since:
        e['since'] = since
    return e


def _ledger(*exits, **kw):
    return {'realized_pnl': kw.get('rpnl', -100.0),
            'unreconciled_exits': list(exits)}


def _found(**by_code):
    """code → (ok, rows) 를 돌려주는 가짜 조회."""
    def _fn(code, f, t):
        return by_code.get(code, (True, []))
    return _fn


def test_confirmed_pnl_lands_in_realized_and_the_entry_goes_away():
    led = _ledger(_exit())
    n = settle_unreconciled_exits(
        led, lookup_range=_found(**{'000111': (True, [
            {'date': '20260105', 'qty': 50, 'amount': -9000.0}])}),
        log=lambda *_: None, log_error=lambda *_: None)

    assert n == 1
    assert led['realized_pnl'] == -9100.0         # -100 + -9,000
    assert 'unreconciled_exits' not in led        # 다 닫히면 키째 사라진다


def test_lookup_failure_leaves_everything_alone():
    """모르는 채로 돈 숫자를 확정하지 않는다."""
    led = _ledger(_exit())
    n = settle_unreconciled_exits(
        led, lookup_range=lambda c, f, t: (False, None),
        log=lambda *_: None, log_error=lambda *_: None)

    assert n == 0
    assert led['realized_pnl'] == -100.0
    assert len(led['unreconciled_exits']) == 1


def test_no_sell_in_the_window_is_not_a_zero():
    """조회는 됐는데 매도가 없다 = 다른 이유로 사라졌다. 0원으로 닫지 않는다."""
    led = _ledger(_exit())
    n = settle_unreconciled_exits(led, lookup_range=_found(),
                                  log=lambda *_: None, log_error=lambda *_: None)

    assert n == 0
    assert led['realized_pnl'] == -100.0
    assert len(led['unreconciled_exits']) == 1


def test_split_across_days_settles_when_the_total_matches():
    led = _ledger(_exit(qty=50))
    n = settle_unreconciled_exits(
        led, lookup_range=_found(**{'000111': (True, [
            {'date': '20260105', 'qty': 30, 'amount': -6000.0},
            {'date': '20260106', 'qty': 20, 'amount': -3000.0}])}),
        log=lambda *_: None, log_error=lambda *_: None)

    assert n == 1
    assert led['realized_pnl'] == -9100.0


def test_ambiguous_quantity_is_left_for_a_human():
    """수량이 어느 조합과도 안 맞으면 고르지 않는다 — 틀린 정산은 미정산보다 나쁘다."""
    led = _ledger(_exit(qty=50))
    n = settle_unreconciled_exits(
        led, lookup_range=_found(**{'000111': (True, [
            {'date': '20260105', 'qty': 10, 'amount': -1.0},
            {'date': '20260106', 'qty': 20, 'amount': -2.0}])}),
        log=lambda *_: None, log_error=lambda *_: None)

    assert n == 0
    assert len(led['unreconciled_exits']) == 1


def test_one_exact_match_wins_over_the_sum():
    """그 종목을 구간 안에 여러 번 팔았어도 수량이 딱 맞는 한 건이면 그것이다."""
    led = _ledger(_exit(qty=50))
    n = settle_unreconciled_exits(
        led, lookup_range=_found(**{'000111': (True, [
            {'date': '20260103', 'qty': 5, 'amount': -500.0},
            {'date': '20260105', 'qty': 50, 'amount': -9000.0}])}),
        log=lambda *_: None, log_error=lambda *_: None)

    assert n == 1
    assert led['realized_pnl'] == -9100.0


def test_partial_settlement_keeps_the_rest():
    led = _ledger(_exit(code='000111', qty=50),
                  _exit(code='000222', qty=1, cost=30000.0))
    n = settle_unreconciled_exits(
        led, lookup_range=_found(**{'000111': (True, [
            {'date': '20260105', 'qty': 50, 'amount': -9000.0}])}),
        log=lambda *_: None, log_error=lambda *_: None)

    assert n == 1
    assert [e['code'] for e in led['unreconciled_exits']] == ['000222']


def test_window_uses_since_when_the_ledger_knows_it():
    """발견일 하나로 물으면 0건이다. 멈춰 있던 구간 전체를 물어야 한다."""
    seen = {}

    def _fn(code, f, t):
        seen[code] = (f, t)
        return True, []

    settle_unreconciled_exits(
        _ledger(_exit(date='2026-01-07', since='2026-01-02')),
        lookup_range=_fn, log=lambda *_: None, log_error=lambda *_: None)

    assert seen['000111'] == ('20260102', '20260107')


def test_window_falls_back_to_a_lookback_for_old_entries():
    """`since` 없이 쌓인 기존 항목도 닫을 수 있어야 한다."""
    seen = {}

    def _fn(code, f, t):
        seen[code] = (f, t)
        return True, []

    settle_unreconciled_exits(
        _ledger(_exit(date='2026-01-07')), lookup_range=_fn,
        lookback_days=30, log=lambda *_: None, log_error=lambda *_: None)

    assert seen['000111'] == ('20251208', '20260107')


def test_empty_ledger_is_a_noop():
    led = {'realized_pnl': 5.0}
    assert settle_unreconciled_exits(led, lookup_range=_found()) == 0
    assert led == {'realized_pnl': 5.0}


# ── 주문 기록이 모호함을 푼다 ───────────────────────────────────────
# 2026-11-23 첫 정산에서 3건이 "수량이 맞는 매도를 특정하지 못했습니다"로 막혔다.
# 한투 조회는 계좌 전체를 보는데 같은 수량 매도가 구간에 세 번 있었고, 앞의 둘은
# 프로그램이 낸 매도였다. 수량만으로는 영원히 못 가린다.

SELLS = {'20261016': 2, '20261023': 2, '20261106': 2}   # 전부 같은 수량


def _range_lookup(calls):
    """구간을 실제로 지키는 가짜 조회. 좁혀 물으면 한 건만 준다."""
    def _fn(code, f, t):
        calls.append((f, t))
        rows = [{'date': d, 'qty': q, 'amount': -1000.0 * int(d[-2:])}
                for d, q in sorted(SELLS.items()) if f <= d <= t]
        return True, rows
    return _fn


def _ambiguous():
    # `since`가 없는 옛 항목이다 — 창이 발견일 −30일까지 벌어져 세 건이 다 들어온다.
    # 실제로 막힌 3건이 정확히 이 모양이었다(2026-11-10 발견, since 없음).
    return _ledger(_exit(code='000111', qty=2, cost=400000.0, date='2026-11-10'))


def test_주문_기록이_없으면_예전처럼_미정산이다():
    """회귀 방지 — 기록을 못 읽었을 때 동작이 바뀌면 안 된다."""
    calls = []
    led = _ambiguous()
    n = settle_unreconciled_exits(led, lookup_range=_range_lookup(calls),
                                  log=lambda *_: None, log_error=lambda *_: None,
                                  orders=None, lookback_days=30)
    assert n == 0
    assert len(led['unreconciled_exits']) == 1
    assert calls == [('20261011', '20261110')], '구간 전체로 물었다'


def test_주문_기록이_수동_매도일을_집으면_닫힌다():
    calls = []
    led = _ambiguous()
    orders = [
        {'time': '2026-10-16 09:01:26', 'symbol': '000111', 'action': 'SELL',
         'qty': 2, 'origin': 'program'},
        {'time': '2026-11-06 08:40:11', 'symbol': '000111', 'action': 'SELL',
         'qty': 2, 'origin': 'manual'},
    ]
    n = settle_unreconciled_exits(led, lookup_range=_range_lookup(calls),
                                  log=lambda *_: None, log_error=lambda *_: None,
                                  orders=orders, lookback_days=30)

    assert n == 1, '주문 기록으로 날짜를 특정했으면 닫혀야 한다'
    assert calls == [('20261106', '20261106')], '그 하루만 물어야 한다'
    assert 'unreconciled_exits' not in led
    assert led['realized_pnl'] == -6100.0          # -100 + (-1000*6)


def test_주문_기록이_프로그램_매도만_가지면_여전히_미정산이다():
    """프로그램 매도를 고르면 원장이 이미 반영한 손익을 두 번 계상한다."""
    led = _ambiguous()
    orders = [{'time': '2026-10-16 09:01:26', 'symbol': '000111',
               'action': 'SELL', 'qty': 2, 'origin': 'program'}]
    n = settle_unreconciled_exits(led, lookup_range=_range_lookup([]),
                                  log=lambda *_: None, log_error=lambda *_: None,
                                  orders=orders, lookback_days=30)
    assert n == 0
    assert len(led['unreconciled_exits']) == 1
