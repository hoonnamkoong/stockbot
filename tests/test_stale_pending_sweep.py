"""조회가 계속 안 되는 어제 주문을 걷어낸다 — 단, 서두르지 않는다.

2026-08-13 발견: 001210의 미체결 매수(34주 @ 5,300, 08-12T15:29 주문)가 다음
거래일 15:31까지 pending에 그대로 남아 180,200원을 묶었다. 그동안 그 종목은
`pending_codes`에 걸려 신규 매수도 막힌다.

`settle_pending_orders`에는 이미 날짜 경계 탈출구가 있다 — "어제 이전 주문의
취소가 실패하면 pending에서 제거하고 사람에게 알린다". 그런데 그 자리에
**도달할 수가 없다.** `reconcile_pending`은 조회 결과가 UNKNOWN이면 `continue`로
빠지므로 취소 목록에 오르지 않고, 따라서 취소를 시도하지도, 날짜 경계 분기에
닿지도 못한다. UNKNOWN이 한 번 굳으면 그 pending은 불멸이 된다.

**그렇다고 1런 만에 지우면 안 된다.** `lookup_execution`이 UNKNOWN을 돌려주는
경우는 사실상 요청 실패 하나뿐이다(미체결은 rows==[] → UNFILLED). 즉 UNKNOWN은
일시적일 수 있고 — 같은 날 러너 egress가 4분간 죽어 KIS 호출 60건이 전부
connect timeout이었다 — 그때 지우면 다음 사이클이면 정상 반영됐을 체결을
원장에서 영구히 잃는다. `reconcile_positions`는 실보유를 원장으로 들여오지
않고 빼기만 하므로 스스로 회복되지 않는다.

매도는 한 겹 더 조심한다. 매도는 주문 시점에 **추정 실현손익을 원장에 이미
더했고**, 그 값은 표시용이 아니라 `effective_budget = budget + realized_pnl`을
통해 다음 실주문 크기에 들어간다. 그냥 지우면 지어낸 숫자가 예산이 된다.
KIS 확정 실현손익으로 갈아끼운 뒤에만 지우고, 못 가져오면 지우지 않는다.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.workers.program_trader import (
    UNKNOWN_SWEEP_RUNS, _pending_buy_cost, settle_pending_orders,
)
from src.trade.executions import FILLED, UNKNOWN
from src.trade.fees import realized_pnl_after_fees

TODAY = '2026-08-13'
YESTERDAY_AT = '2026-08-12T15:29:21'

QTY, PRICE, AVG = 34, 5300.0, 5000.0
# 매도 주문 시점에 accrue_realized_pnl이 원장에 더해 둔 추정치.
ESTIMATE = realized_pnl_after_fees(QTY, AVG, PRICE)


class _AlertSpy:
    def __init__(self):
        self.calls = []

    def __call__(self, key, text, now, **kw):
        self.calls.append((key, text))
        return True


def _ledger(ordered_at=YESTERDAY_AT, side='buy', realized=0.0):
    return {
        'positions': {},
        'realized_pnl': realized,
        'pending_orders': {
            '001210': {'odno': 'OD1', 'side': side, 'qty': QTY, 'price': PRICE,
                       'ordered_at': ordered_at,
                       'avg_price': AVG if side == 'sell' else None,
                       'tag': None, 'snapshot': {}, 'applied_qty': 0},
        },
    }


def _settle(ledger, alert, lookup=None, realized=None):
    settle_pending_orders(
        ledger, TODAY, lookup or (lambda odno: (UNKNOWN, None)),
        lambda *a: True, lambda m: None, lambda m: None,
        now_kst=datetime(2026, 8, 13, 9, 5), alert=alert,
        quote=lambda code: {'price': 9999},   # 판단가와 다르게 → _keep_resting 비켜감
        realized=realized)


def _settle_n(ledger, alert, n, **kw):
    for _ in range(n):
        _settle(ledger, alert, **kw)


# ── 연속 UNKNOWN 게이트 ──────────────────────────────────────────────

def test_one_bad_lookup_does_not_delete_the_order():
    """08-13의 egress 사고가 이 경로다. 여기서 지우면 다음 사이클이면 정상
    반영됐을 체결을 영구히 잃는다."""
    ledger = _ledger()
    alert = _AlertSpy()

    _settle(ledger, alert)

    assert '001210' in ledger['pending_orders']
    assert alert.calls == []


def test_swept_only_after_the_streak():
    ledger = _ledger()
    alert = _AlertSpy()

    _settle_n(ledger, alert, UNKNOWN_SWEEP_RUNS - 1)
    assert '001210' in ledger['pending_orders'], '아직 이르다'

    _settle(ledger, alert)
    assert ledger['pending_orders'] == {}
    assert len(alert.calls) == 1


def test_a_successful_lookup_resets_the_streak():
    """조회가 한 번이라도 되면 정상 경로가 처리한다. 그때까지의 실패를
    누적해 두면 나중에 한 번 더 실패한 순간 지워진다."""
    ledger = _ledger()
    alert = _AlertSpy()

    _settle_n(ledger, alert, UNKNOWN_SWEEP_RUNS - 1)
    # 조회 성공(FILLED)이 끼어든다 — reconcile이 정상 처리하므로 pending은 비고,
    # 남아 있었더라도 카운터는 0으로 돌아가야 한다.
    _settle(ledger, alert, lookup=lambda odno: (FILLED, {'qty': QTY, 'price': PRICE}))

    assert alert.calls == [], '정상 경로가 처리했으므로 경보가 없어야 한다'


def test_yesterdays_filled_order_is_never_swept():
    """스윕이 실제 체결을 먹지 않는다 — 이 PR의 핵심 안전성 주장이다."""
    ledger = _ledger()
    alert = _AlertSpy()

    _settle_n(ledger, alert, UNKNOWN_SWEEP_RUNS + 2,
              lookup=lambda odno: (FILLED, {'qty': QTY, 'price': PRICE}))

    assert ledger['positions']['001210']['quantity'] == QTY
    assert alert.calls == []


def test_todays_order_is_left_alone_however_many_failures():
    """오늘 낸 주문은 아직 살아 있다. 조회 실패로 지우면 방금 낸 주문을
    원장에서 잃고, 그러면 같은 종목을 또 산다(이중 지출)."""
    ledger = _ledger(ordered_at=f'{TODAY}T09:03:11')
    alert = _AlertSpy()

    _settle_n(ledger, alert, UNKNOWN_SWEEP_RUNS + 2)

    assert '001210' in ledger['pending_orders']
    assert alert.calls == []


def test_unparsable_ordered_at_is_not_swept():
    """시각을 못 읽는 것과 '어제 주문이다'는 다르다.

    빈 문자열만으로는 부족하다 — 문자열 비교로 때우면 '(없음)' 같은 값이
    어떤 날짜보다도 작아서 조용히 '어제 주문'이 된다(실제로 그렇게 짰다가
    기존 테스트에 걸렸다)."""
    for bad in ('', '(없음)', 'unknown', '2026-13-99'):
        ledger = _ledger(ordered_at=bad)
        alert = _AlertSpy()

        _settle_n(ledger, alert, UNKNOWN_SWEEP_RUNS + 1)

        assert '001210' in ledger['pending_orders'], bad
        assert alert.calls == [], bad


# ── 매수 ─────────────────────────────────────────────────────────────

def test_sweeping_a_buy_frees_the_budget():
    """묶여 있던 예산이 풀리는 것이 이 정리의 목적이다(001210은 180,200원)."""
    ledger = _ledger()
    assert _pending_buy_cost(ledger['pending_orders']) == QTY * PRICE

    _settle_n(ledger, _AlertSpy(), UNKNOWN_SWEEP_RUNS)

    assert _pending_buy_cost(ledger['pending_orders']) == 0


def test_buy_alert_tells_a_human_what_to_check():
    ledger = _ledger()
    alert = _AlertSpy()

    _settle_n(ledger, alert, UNKNOWN_SWEEP_RUNS)

    key, text = alert.calls[0]
    assert key == 'pending_stale_001210'
    assert 'OD1' in text and '매수' in text


def test_sweeping_a_buy_does_not_touch_positions():
    """부분체결분은 이미 positions에 반영돼 있다."""
    ledger = _ledger()
    ledger['positions']['001210'] = {'quantity': 10, 'avg_price': 5300.0}

    _settle_n(ledger, _AlertSpy(), UNKNOWN_SWEEP_RUNS)

    assert ledger['positions']['001210']['quantity'] == 10


# ── 매도: 추정치를 확정값으로 갈아끼운 뒤에만 지운다 ─────────────────

def test_sell_is_kept_when_the_confirmation_lookup_fails():
    """모르는 채로 돈 숫자를 확정하지 않는다. 지우면 추정치가 영구히 굳고,
    그 값이 effective_budget을 통해 다음 주문 크기가 된다."""
    ledger = _ledger(side='sell', realized=ESTIMATE)
    alert = _AlertSpy()

    _settle_n(ledger, alert, UNKNOWN_SWEEP_RUNS + 2,
              realized=lambda code, date: (False, None))

    assert '001210' in ledger['pending_orders']
    assert alert.calls == []
    assert ledger['realized_pnl'] == ESTIMATE, '추정치를 확정으로 굳히지 않는다'


def test_sell_estimate_is_replaced_by_the_confirmed_amount():
    """KIS 확정 실현손익이 원장에 그대로 남아야 한다 — 추정치는 사라진다."""
    ledger = _ledger(side='sell', realized=ESTIMATE)

    _settle_n(ledger, _AlertSpy(), UNKNOWN_SWEEP_RUNS,
              realized=lambda code, date: (True, {'qty': QTY, 'amount': 7777.0}))

    assert ledger['pending_orders'] == {}
    assert ledger['realized_pnl'] == 7777.0


def test_sell_that_never_filled_backs_the_estimate_out_and_restores_the_position():
    """조회는 됐는데 그 날 매도가 없다 = 안 팔렸다. 추정 손익을 통째로
    되돌리고 포지션을 되살려야 한다 — 실계좌에는 아직 그 주식이 있다."""
    ledger = _ledger(side='sell', realized=ESTIMATE)

    _settle_n(ledger, _AlertSpy(), UNKNOWN_SWEEP_RUNS,
              realized=lambda code, date: (True, None))

    assert ledger['realized_pnl'] == 0.0
    assert ledger['positions']['001210']['quantity'] == QTY
    assert ledger['positions']['001210']['avg_price'] == AVG


def test_sell_alert_does_not_give_the_buy_side_instruction():
    """매수와 매도는 사람이 확인할 것이 정반대다. 매도에 '체결됐다면 원장에
    없다'를 주면 틀린 지시가 된다."""
    ledger = _ledger(side='sell', realized=ESTIMATE)
    alert = _AlertSpy()

    _settle_n(ledger, alert, UNKNOWN_SWEEP_RUNS,
              realized=lambda code, date: (True, {'qty': QTY, 'amount': 7777.0}))

    _, text = alert.calls[0]
    assert '매도' in text
    assert 'KIS 확정값' in text
