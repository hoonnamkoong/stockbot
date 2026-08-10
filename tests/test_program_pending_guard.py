"""미체결 주문 필터 테스트 (pending_codes guard)."""
import pytest


class FakeSim:
    """테스트용 모의 심."""
    def __init__(self):
        self.state = None
        self.save_state = None
        self.log_trade = None
        self.buy = None
        self.sell = None


def make_snapshot(cash=3_000_000, portfolio=None):
    """테스트용 스냅샷 상태."""
    return {
        'cash': float(cash),
        'portfolio': portfolio or {},
        'invested': 0,
    }


def test_pending_guard_buy_blocked_with_pending_codes():
    """미체결 주문이 걸린 종목은 매수를 거부한다."""
    from src.pipeline.workers.program_trader import _make_adapter

    sim = FakeSim()
    snapshot = make_snapshot(cash=1_000_000)
    pending_codes = {'005930'}  # 삼성전자 미체결

    orders = _make_adapter(sim, snapshot, '2026-08-10', real_holdings={}, pending_codes=pending_codes)

    # 미체결 종목으로 매수 시도
    result = sim.buy('005930', '삼성전자', 70_000, 10)
    assert result is False, "미체결 주문 걸린 종목의 매수를 거부해야 함"
    assert len(orders) == 0, "주문이 기록되면 안 됨"


def test_pending_guard_buy_allowed_without_pending_codes():
    """미체결이 아닌 종목은 매수를 허용한다."""
    from src.pipeline.workers.program_trader import _make_adapter

    sim = FakeSim()
    snapshot = make_snapshot(cash=1_000_000)
    pending_codes = {'005930'}  # 삼성전자만 미체결

    orders = _make_adapter(sim, snapshot, '2026-08-10', real_holdings={}, pending_codes=pending_codes)

    # 다른 종목으로 매수 시도
    result = sim.buy('000660', 'SK하이닉스', 100_000, 5)
    assert result is True, "미체결 아닌 종목의 매수를 허용해야 함"
    assert len(orders) == 1, "주문이 기록되어야 함"
    assert orders[0]['code'] == '000660'


def test_pending_guard_empty_codes():
    """pending_codes가 비었으면 기존 동작 유지."""
    from src.pipeline.workers.program_trader import _make_adapter

    sim = FakeSim()
    snapshot = make_snapshot(cash=1_000_000)
    pending_codes = set()

    orders = _make_adapter(sim, snapshot, '2026-08-10', real_holdings={}, pending_codes=pending_codes)

    # 아무 종목이나 매수 가능
    result = sim.buy('005930', '삼성전자', 70_000, 10)
    assert result is True, "pending_codes가 비었으면 아무 종목이나 매수 가능"
    assert len(orders) == 1


def test_pending_guard_default_backward_compatible():
    """기존 호출(pending_codes 없음)도 동작해야 함(기본값)."""
    from src.pipeline.workers.program_trader import _make_adapter

    sim = FakeSim()
    snapshot = make_snapshot(cash=1_000_000)

    # pending_codes 인자 없이 호출
    orders = _make_adapter(sim, snapshot, '2026-08-10', real_holdings={})

    # 정상 작동
    result = sim.buy('005930', '삼성전자', 70_000, 10)
    assert result is True, "기본값에서 기존 동작 유지"
    assert len(orders) == 1


def test_sell_is_not_blocked_by_pending():
    """매도는 pending 종목이어도 차단되지 않는다 (청산은 무조건 해야 함)."""
    from src.pipeline.workers.program_trader import _make_adapter

    sim = FakeSim()
    # 포트폴리오에 종목이 이미 있는 상태
    snapshot = make_snapshot(
        cash=1_000_000,
        portfolio={
            '005930': {
                'name': '삼성전자',
                'quantity': 10,
                'avg_price': 70_000,
                'peak_price': 70_000,
                'entry_date': '2026-08-10',
                'is_scaled_out': False,
            }
        }
    )
    pending_codes = {'005930'}  # 매도하려는 종목이 미체결

    orders = _make_adapter(sim, snapshot, '2026-08-10', real_holdings={}, pending_codes=pending_codes)

    # 미체결 종목이어도 매도는 허용됨
    result = sim.sell('005930', 75_000, quantity=5)
    assert result is True, "pending 종목도 매도는 허용되어야 함(청산 우선)"
    assert len(orders) == 1, "매도 주문이 기록되어야 함"
    assert orders[0]['side'] == 'sell'
    assert orders[0]['code'] == '005930'
