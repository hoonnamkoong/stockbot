"""락이 '주문 전에' 잡히는지 — 헬퍼 단위 테스트로는 못 잡는 배선을 검증한다.

_lock_is_live/_claim_payload가 옳아도 run_program_trading이 그걸 주문 뒤에 부르면
아무 소용이 없다. 여기서는 실제 호출 순서와 skip 조건을 본다.
"""
import os
import sys
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers import program_trader as pt

NOW = datetime(2026, 8, 6, 10, 30, 0)


def _cfg(sim_id='sim4_bull_daytrading'):
    return {'enabled': True, 'selected_sim': sim_id, 'budget': 2_000_000}


def _base_ledger(**over):
    d = {'positions': {}, 'last_run': None, 'sim': None, 'realized_pnl': 0,
         'cooldown_codes': {}, 'turn': {}, 'lock_run_id': None, 'lock_at': None}
    d.update(over)
    return d


def _run(ledger, write_results=None, balance=None):
    """run_program_trading을 최소 스텁으로 돌리고 (호출순서, write 인자들)을 돌려준다."""
    calls = []
    writes = []
    results = list(write_results or [(True, 'sha-2')])

    def fake_write(led, sha, log=print, retry_on_conflict=True):
        calls.append('write')
        writes.append({'ledger': dict(led), 'sha': sha,
                       'retry_on_conflict': retry_on_conflict})
        return results.pop(0) if results else (True, 'sha-n')

    def fake_balance():
        calls.append('balance')
        return balance if balance is not None else {'deposit': 2_000_000, 'holdings': []}

    with mock.patch.object(pt, '_read_config_fresh', return_value=_cfg()), \
         mock.patch.object(pt, '_read_ledger_fresh', return_value=(ledger, 'sha-1')), \
         mock.patch.object(pt, '_write_ledger', side_effect=fake_write), \
         mock.patch.object(pt, '_new_run_id', return_value='run-under-test'), \
         mock.patch('src.trade.balance.get_balance', side_effect=fake_balance), \
         mock.patch('src.strategy.registry.get_tradeable_simulator_ids',
                    return_value=['sim4_bull_daytrading']), \
         mock.patch('src.strategy.registry.get_simulator_by_id', return_value=None):
        pt.run_program_trading([], is_market_hours=True, now_kst=NOW,
                               log=lambda *a: None, log_error=lambda *a: None)
    return calls, writes


def test_lock_is_claimed_before_balance_and_orders():
    """락 선점(write)이 잔고 조회보다 먼저 일어나야 한다.

    잔고 조회부터 하면 그 사이 다른 런이 같은 원장을 읽고 들어온다.
    """
    calls, writes = _run(_base_ledger())

    assert calls[0] == 'write', f'첫 동작이 락 선점이어야 한다: {calls}'
    assert 'balance' in calls
    assert calls.index('write') < calls.index('balance')


def test_claim_write_must_not_retry_on_conflict():
    """선점 PUT이 충돌 시 재시도하면 남의 락을 덮어써 중복 주문이 난다."""
    _, writes = _run(_base_ledger())

    assert writes[0]['retry_on_conflict'] is False
    assert writes[0]['ledger']['lock_run_id'] == 'run-under-test'


def test_skips_entirely_when_another_run_holds_a_live_lock():
    """살아있는 락이 있으면 원장을 건드리지도, 잔고를 조회하지도 않는다."""
    live = _base_ledger(lock_run_id='other-run',
                        lock_at=(NOW - timedelta(seconds=30)).isoformat())

    calls, writes = _run(live)

    assert calls == [], f'아무것도 하지 않아야 한다: {calls}'
    assert writes == []


def test_proceeds_when_lock_lease_expired():
    """죽은 런이 남긴 락은 회수하고 진행한다."""
    stale = _base_ledger(
        lock_run_id='dead-run',
        lock_at=(NOW - timedelta(minutes=pt._LOCK_LEASE_MIN + 1)).isoformat())

    calls, _ = _run(stale)

    assert calls and calls[0] == 'write'


def test_aborts_when_claim_loses_the_race():
    """선점 PUT이 충돌하면 잔고 조회까지 가지 않고 즉시 포기한다."""
    calls, writes = _run(_base_ledger(), write_results=[(False, None)])

    assert calls == ['write'], f'선점 실패 후 더 진행하면 안 된다: {calls}'
    assert 'balance' not in calls


def test_releases_lock_when_balance_fails():
    """잔고 조회 실패(오늘 10:50 KIS 타임아웃 실측)에서 락을 쥔 채 나가면
    다음 사이클들이 리스 만료까지 전부 막힌다."""
    calls, writes = _run(_base_ledger(), balance={'error': 'timeout'})

    assert calls.count('write') == 2, f'선점 + 해제 두 번이어야 한다: {calls}'
    assert writes[-1]['ledger']['lock_run_id'] is None
    assert writes[-1]['ledger']['lock_at'] is None


def test_releases_lock_when_simulator_cannot_be_built():
    """심 인스턴스 생성 실패 경로(get_simulator_by_id=None)도 락을 놓아야 한다."""
    calls, writes = _run(_base_ledger())

    assert writes[-1]['ledger']['lock_run_id'] is None


def test_dup_guard_still_skips_before_touching_the_lock():
    """중복가드에 걸리면 락 선점 자체를 하지 않는다 (불필요한 PUT 방지)."""
    recent = _base_ledger(last_run=(NOW - timedelta(seconds=10)).isoformat())

    calls, writes = _run(recent)

    assert calls == []
    assert writes == []


# ── 락 선점 이후, 주문 루프까지 가는 전체 경로 ──────────────────────
# 위 _run()은 get_simulator_by_id=None으로 항상 "심 생성 실패" 조기 종료 경로만
# 탄다. 여기서는 실제로 주문 루프까지 가는 경로를 구성해서, 어드버서리얼
# 리뷰에서 나온 두 지점을 검증한다:
#   1) 정합/스냅샷 단계(reconcile_positions~_make_adapter)에서 예외가 나도 락을
#      놓는가 (전에는 이 구간이 개별 가드가 없어 리스 만료까지 락이 안 풀렸다)
#   2) 주문 루프가 스스로 데드라인을 넘기면 신규 주문을 멈추는가 (리스 만료를
#      기다리다 다음 런과 겹쳐서 중복 주문이 나는 걸 막는 장치)

class _FakeSim:
    state = {'portfolio': {}}

    def run(self, candidates, current_prices=None):
        pass


def _run_full(ledger, orders, monotonic_seq=None, raise_in='none',
             place_order_result=None):
    """reconcile_positions~주문 루프까지 실제로 타는 시나리오."""
    calls = []
    writes = []

    def fake_write(led, sha, log=print, retry_on_conflict=True):
        calls.append('write')
        writes.append({'ledger': dict(led)})
        return True, 'sha-n'

    def fake_reconcile(*a, **k):
        if raise_in == 'reconcile':
            raise RuntimeError('reconcile boom')
        return {}

    def fake_make_adapter(*a, **k):
        if raise_in == 'make_adapter':
            raise RuntimeError('adapter boom')
        return orders

    patches = [
        mock.patch.object(pt, '_read_config_fresh', return_value=_cfg()),
        mock.patch.object(pt, '_read_ledger_fresh', return_value=(ledger, 'sha-1')),
        mock.patch.object(pt, '_write_ledger', side_effect=fake_write),
        mock.patch.object(pt, '_new_run_id', return_value='run-under-test'),
        mock.patch('src.trade.balance.get_balance',
                   return_value={'deposit': 2_000_000, 'holdings': []}),
        mock.patch('src.strategy.registry.get_tradeable_simulator_ids',
                   return_value=['sim4_bull_daytrading']),
        mock.patch('src.strategy.registry.get_simulator_by_id', return_value=_FakeSim()),
        mock.patch.object(pt, 'reconcile_positions', side_effect=fake_reconcile),
        mock.patch.object(pt, '_resolve_candidates', return_value=[]),
        mock.patch.object(pt, '_make_adapter', side_effect=fake_make_adapter),
        mock.patch.object(pt, 'check_buy_drift', return_value=(True, None, '')),
        mock.patch('src.trade_executor.place_order_via_vercel',
                   return_value=place_order_result or {'success': True, 'data': {}}),
        mock.patch('src.trade_executor.append_order_history'),
    ]
    if monotonic_seq is not None:
        # 마지막 값을 계속 되돌려준다. 고정 길이 리스트를 그대로 쓰면
        # run_program_trading이 monotonic()을 한 번 더 부르게 되는 변경마다
        # 이 테스트가 StopIteration으로 깨진다 — 검증하려는 건 호출 횟수가
        # 아니라 "데드라인을 넘겼을 때의 동작"이다.
        seq = list(monotonic_seq)

        def _clock():
            return seq.pop(0) if len(seq) > 1 else seq[0]

        patches.append(mock.patch.object(pt.time, 'monotonic', side_effect=_clock))

    with _apply(patches):
        pt.run_program_trading([], is_market_hours=True, now_kst=NOW,
                               log=lambda *a: None, log_error=lambda *a: None)
    return calls, writes


class _apply:
    """여러 mock.patch를 with 없이 리스트로 받아 한꺼번에 걸기 위한 헬퍼."""
    def __init__(self, patches):
        self._patches = patches

    def __enter__(self):
        for p in self._patches:
            p.start()

    def __exit__(self, *a):
        for p in reversed(self._patches):
            p.stop()


def _order(code='005930', side='buy', qty=1, price=70000):
    return {'code': code, 'side': side, 'qty': qty, 'price': price}


def test_exception_between_reconcile_and_order_prep_releases_lock():
    """정합 단계에서 터져도 락을 놓아야 한다 — 이전엔 이 구간에 가드가 없어
    리스(4분) 만료까지 다음 사이클이 전부 막혔다."""
    calls, writes = _run_full(_base_ledger(), orders=[], raise_in='reconcile')

    assert calls.count('write') == 2, f'선점 + 해제 두 번이어야 한다: {calls}'
    assert writes[-1]['ledger']['lock_run_id'] is None


def test_exception_in_adapter_construction_releases_lock():
    """스냅샷~어댑터 구성 단계도 동일하게 보호돼야 한다."""
    calls, writes = _run_full(_base_ledger(), orders=[], raise_in='make_adapter')

    assert calls.count('write') == 2
    assert writes[-1]['ledger']['lock_run_id'] is None


def test_order_loop_stops_placing_new_orders_past_deadline():
    """루프 자체가 데드라인을 넘기면(느린 KIS/Vercel), 리스 만료를 기다리지 않고
    스스로 신규 주문을 멈춘다."""
    orders = [_order('005930'), _order('000660'), _order('035420')]
    # 1번째 monotonic 호출=claim 시각(0), 그 다음 루프 진입 시 데드라인 초과(999)로
    # 첫 주문에서 바로 중단돼야 한다.
    calls, writes = _run_full(_base_ledger(), orders=orders, monotonic_seq=[0, 999])

    final = writes[-1]['ledger']
    assert final.get('positions') == {}, '주문이 하나도 실행되지 않아야 한다'
    assert final['lock_run_id'] is None, '중단 후에도 락은 정상적으로 풀려야 한다'


def test_order_loop_completes_normally_within_deadline():
    """평소(데드라인 안)에는 주문이 정상적으로 다 처리된다."""
    orders = [_order('005930')]
    # claim(0) → 루프 체크(1초 경과) → 여유 있음
    calls, writes = _run_full(_base_ledger(), orders=orders, monotonic_seq=[0, 1, 1])

    final = writes[-1]['ledger']
    assert final['lock_run_id'] is None
