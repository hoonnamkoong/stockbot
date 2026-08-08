"""주문 준비가 예산을 다 먹은 사이클은 조용히 지나가면 안 된다.

_ORDER_LOOP_DEADLINE_SEC는 원래 "주문 루프가 리스보다 오래 살아남지 않게" 하는
장치다. 그런데 준비 단계(잔고 조회 → 정합 → 유니버스 보강 → 심 실행)가 느려져
그것만으로 예산을 넘기면, 루프가 첫 바퀴에서 곧바로 끊겨 **체결 0건인데 로그는
정상으로 보이는** 상태가 된다. 매매가 멈춘 걸 아무도 모른다.

정상 준비 시간은 10초대다(2026-08-07 실측 Stage 0.5 = 12.4초).
"""
import os
import sys
from datetime import datetime
from unittest import mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.workers import program_trader as pt

NOW = datetime(2026, 8, 10, 10, 30)


class _Sim:
    IS_ANALYZER = False

    def __init__(self):
        self.state = {'portfolio': {}}

    def get_universe(self):
        return [{'code': '005930', 'price': 70000}]

    def run(self, candidates, current_prices=None):
        pass


def _run(orders, clock):
    """run_program_trading을 최소 스텁으로 돌린다. clock: time.monotonic 대역."""
    ledger = {'positions': {}, 'last_run': None, 'sim': None, 'realized_pnl': 0,
              'cooldown_codes': {}, 'turn': {}, 'lock_run_id': None, 'lock_at': None}
    errors = []
    with mock.patch.object(pt, '_read_config_fresh', return_value={
             'enabled': True, 'selected_sim': 'sim4_bull_daytrading', 'budget': 2_000_000}), \
         mock.patch.object(pt, '_read_ledger_fresh', return_value=(ledger, 'sha-1')), \
         mock.patch.object(pt, '_write_ledger', return_value=(True, 'sha-2')), \
         mock.patch.object(pt, '_make_adapter', return_value=orders), \
         mock.patch.object(pt.time, 'monotonic', side_effect=clock), \
         mock.patch('src.trade.balance.get_balance',
                    return_value={'deposit': 2_000_000, 'holdings': []}), \
         mock.patch('src.strategy.registry.get_tradeable_simulator_ids',
                    return_value=['sim4_bull_daytrading']), \
         mock.patch('src.strategy.registry.get_simulator_by_id', return_value=_Sim()), \
         mock.patch.object(pt.alerts, 'send_alert_once') as alert:
        pt.run_program_trading([], is_market_hours=True, now_kst=NOW,
                               log=lambda *a: None,
                               log_error=lambda m: errors.append(str(m)),
                               enrich=lambda s: s)
    return alert, errors


def test_alerts_when_preparation_alone_blows_the_budget():
    order = {'code': '005930', 'side': 'buy', 'qty': 1, 'price': 70000}
    # 클레임 시각 0초 → 준비가 끝난 시점이 이미 예산 초과
    clock = iter([0.0] + [pt._ORDER_LOOP_DEADLINE_SEC + 30] * 20)
    alert, errors = _run([order], lambda: next(clock))

    alert.assert_called_once()
    assert alert.call_args[0][0] == 'program_prep_over_budget'
    assert any('주문을 내지 않습니다' in e for e in errors)


def test_no_alert_on_a_normal_fast_cycle():
    """정상 사이클(준비 12초대)에서는 울리지 않는다 — 울리면 둔감해진다."""
    order = {'code': '005930', 'side': 'buy', 'qty': 1, 'price': 70000}
    clock = iter([0.0] + [12.4] * 20)
    alert, _ = _run([order], lambda: next(clock))

    alert.assert_not_called()
