"""주문은 나갔는데 원장 기록이 실패하면, 그건 사람이 즉시 알아야 하는 사고다.

`_write_ledger`는 실패를 로그 한 줄로만 남기고 `(False, None)`을 돌려준다. 주문
루프를 다 돈 뒤의 마지막 PUT이 실패하면 pending_orders(odno)·positions·
realized_pnl이 통째로 유실되고, 다음 사이클은 그 종목을 **안 산 것으로 보고 다시
산다**(2026-07 진흥기업 5연속 매수와 같은 형태). 이 파일의 다른 돈 사건(락 상실·
주문 시스템 고장·odno 결손)에는 전부 alerts가 붙어 있는데 이 경로만 print였다.

쿨다운을 걸지 않는 이유: 사람이 KIS 체결 내역과 한 건씩 대조해야 하므로 건마다
울려야 한다. 대조하려면 **이번 사이클에 낸 주문 목록**이 알림 본문에 있어야 한다.

그리고 잔고 스냅샷(real_holdings)에 없는 코드가 positions에 생길 수 있다 —
positions는 스냅샷을 찍은 뒤 settle_pending_orders가 갱신하기 때문이다. 그때
`real_holdings[c]`가 KeyError를 내면 손절을 포함한 사이클 전체가 죽는다.
"""
import os
import sys
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.workers import program_trader as pt

NOW = datetime(2026, 8, 10, 10, 30)
SELL_ORDER = {'code': '005930', 'side': 'sell', 'qty': 1, 'price': 70000,
              'name': '삼성전자', 'reason': '손절'}


class _Sim:
    IS_ANALYZER = False

    def __init__(self):
        self.state = {'portfolio': {}}

    def get_universe(self):
        # tick_power를 채워 둔다 — 비면 '체결강도 전량 결손' 경보가 함께 울려
        # 이 파일이 재려는 경보와 섞인다.
        return [{'code': '005930', 'price': 70000, 'tick_power': 130.0}]

    def run(self, candidates, current_prices=None):
        pass


def _run(write_results, orders=(SELL_ORDER,), settle=None):
    """run_program_trading 한 사이클을 스텁으로 돌린다.

    write_results: _write_ledger의 반환값 side_effect(첫 호출은 락 선점이다).
    settle: settle_pending_orders 대역(없으면 진짜를 쓴다).
    반환: (send_alert mock, log_error 목록, place_order mock, _write_ledger mock)
    """
    ledger = {
        'positions': {'005930': {'quantity': 1, 'avg_price': 60000, 'name': '삼성전자',
                                 'entry_date': '2026-08-10', 'peak_price': 70000}},
        'last_run': None, 'sim': None, 'realized_pnl': 0, 'cooldown_codes': {},
        'turn': {}, 'pending_orders': {}, 'lock_run_id': None, 'lock_at': None,
    }
    balance = {'deposit': 2_000_000, 'holdings': [
        {'code': '005930', 'name': '삼성전자', 'qty': 1, 'avg_price': 60000,
         'current_price': 70000}]}
    errors = []
    order_res = {'success': True, 'data': {'odno': 'OD1'}}

    stack = [
        mock.patch.object(pt, '_read_config_fresh', return_value={
            'enabled': True, 'selected_sim': 'sim4_bull_daytrading', 'budget': 2_000_000}),
        mock.patch.object(pt, '_read_ledger_fresh', return_value=(ledger, 'sha-1')),
        mock.patch.object(pt, '_write_ledger', side_effect=list(write_results)),
        mock.patch.object(pt, '_make_adapter', return_value=list(orders)),
        mock.patch('src.trade.balance.get_balance', return_value=balance),
        mock.patch('src.strategy.registry.get_tradeable_simulator_ids',
                   return_value=['sim4_bull_daytrading']),
        mock.patch('src.strategy.registry.get_simulator_by_id', return_value=_Sim()),
        mock.patch('src.trade_executor.place_order_via_vercel', return_value=order_res),
        mock.patch('src.trade_executor.append_order_history'),
        mock.patch.object(pt.alerts, 'send_alert'),
        mock.patch.object(pt.alerts, 'send_alert_once'),
    ]
    if settle is not None:
        stack.append(mock.patch.object(pt, 'settle_pending_orders', side_effect=settle))

    started = [s.start() for s in stack]
    try:
        pt.run_program_trading([], is_market_hours=True, now_kst=NOW,
                               log=lambda *a: None,
                               log_error=lambda m: errors.append(str(m)),
                               enrich=lambda s: s)
    finally:
        for s in reversed(stack):
            s.stop()
    # started 순서는 stack 순서와 같다
    return started[9], errors, started[7], started[2]


def test_원장_기록_실패는_주문목록과_함께_사람에게_간다():
    """기록 실패 = 다음 사이클 재매수 위험. 대조할 주문 목록이 본문에 있어야 한다."""
    send_alert, errors, place_order, write_ledger = _run(
        [(True, 'sha-1'), (False, None), (False, None)])

    assert place_order.called, '주문은 실제로 나갔어야 이 시나리오가 성립한다'
    assert send_alert.called, '원장 기록 실패는 print로 끝나면 안 된다'
    body = send_alert.call_args[0][0]
    assert '005930' in body and '1주' in body and '매도' in body, \
        f'KIS 체결내역과 대조하려면 종목·수량·방향이 필요하다: {body}'
    assert errors, '로그에도 남아야 한다'


def test_기록_실패는_한_번_재시도한다():
    """일시적 실패(HTTP 5xx·sha 경합)에 알림부터 울리면 둔감해진다."""
    _, _, _, write_ledger = _run([(True, 'sha-1'), (False, None), (False, None)])
    assert write_ledger.call_count >= 3, '락 선점 1 + 기록 1 + 재시도 1'


def test_재시도가_성공하면_알림은_가지_않는다():
    send_alert, _, _, write_ledger = _run(
        [(True, 'sha-1'), (False, None), (True, 'sha-2')])
    assert not send_alert.called, '결국 기록됐으면 사고가 아니다'


def test_정상_기록이면_알림이_없다():
    send_alert, _, place_order, _ = _run([(True, 'sha-1'), (True, 'sha-2')])
    assert place_order.called
    assert not send_alert.called


def test_주문이_없는_사이클의_기록_실패도_알린다():
    """주문 0건이어도 정산 결과(realized_pnl·pending)가 유실된다."""
    send_alert, _, _, _ = _run([(True, 'sha-1'), (False, None), (False, None)],
                               orders=())
    assert send_alert.called


def test_잔고에_없는_포지션이_있어도_사이클이_죽지_않는다():
    """real_holdings는 스냅샷이고 positions는 그 뒤 settle_pending_orders가 갱신한다.
    그 사이 체결된 매수는 positions에만 있다 — KeyError로 손절까지 같이 죽었다."""
    def _settle(ledger, *a, **k):
        ledger['positions']['999999'] = {
            'quantity': 5, 'avg_price': 1000, 'name': '방금체결',
            'entry_date': '2026-08-10', 'peak_price': 1000}

    send_alert, errors, place_order, _ = _run(
        [(True, 'sha-1'), (True, 'sha-2')], settle=_settle)

    assert not any('주문 준비/심 실행 실패' in e for e in errors), \
        f'KeyError로 사이클이 통째로 죽으면 안 된다: {errors}'
    assert place_order.called, '손절 주문은 나갔어야 한다'
