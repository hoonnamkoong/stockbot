"""심2 사이징을 다른 매매심과 맞춘다.

2026-08-03에 심2는 거래가 0건이었다. 원인은 신호가 아니라 현금이었다 —
보유 10종목에 현금 36,234원(NAV의 1.2%)이라 어떤 신호가 와도 base.buy가
현금 부족으로 조용히 False를 반환했다. 심2에만 보유 종목 수 상한이 없고
종목당 NAV/10을 투입해 자금을 100% 소진할 수 있었다.
다른 매매심은 전부 NAV×15% × 최대 6종목 = 90%다.
"""
import os, sys
from datetime import timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators.base_simulator import get_kst_now
from src.strategy.simulators.sim2_spillover import (
    MAX_HOLDINGS, POSITION_WEIGHT, TIMEOUT_DAYS, SectorSpilloverSimulator,
)


def _sim(tmp_path, portfolio=None, cash=3_000_000):
    s = SectorSpilloverSimulator(initial_cash=3_000_000)
    s.state_file = str(tmp_path / "s.json")
    s.csv_file = str(tmp_path / "s.csv")
    s.log_file = str(tmp_path / "s.log")
    s.state = {'initial_cash': 3_000_000, 'cash': cash, 'invested': 0,
               'portfolio': portfolio or {}, 'peak_nav': 3_000_000, 'total_fees': 0,
               'history': [3_000_000], 'daily_trades': [], 'market_index_healthy': True,
               'cooldown_codes': {}}
    return s


def _candidate(code, name, price=1000):
    """스코어 60 이상이 확실한 후보(수급 A 40점 + 발산 B 40점)."""
    return {'code': code, 'name': name, 'price': price, 'amount': 5_000_000_000,
            'change_rate': '+1.00%', 'frgn_fake_ntby_qty': 10_000,
            'orgn_fake_ntby_qty': 10_000}


def _holding(code, qty=10, price=1000, entry_date=None):
    """entry_date 기본값은 '오늘'이다 — 타임스톱에 걸리지 않는 갓 산 보유.

    타임스톱을 보려는 테스트만 명시적으로 옛 날짜를 넘긴다. 예전엔 여기에
    '2026-08-03'이 박혀 있었는데, 그건 슬롯·사이징을 보려던 테스트가
    엉뚱하게 타임스톱에 걸린다는 뜻이다.
    """
    return {'name': code, 'quantity': qty, 'avg_price': price,
            'entry_date': entry_date or get_kst_now().strftime('%Y-%m-%d'),
            'peak_price': price, 'is_scaled_out': False}


def test_stops_buying_at_max_holdings(tmp_path):
    """슬롯이 다 찼으면 신호가 있어도 더 사지 않는다."""
    held = {f'00000{i}': _holding(f'00000{i}') for i in range(1, MAX_HOLDINGS + 1)}
    s = _sim(tmp_path, portfolio=held)
    prices = {c: 1000 for c in held}

    s.run([_candidate('111111', '신규A'), _candidate('222222', '신규B')], prices)

    assert '111111' not in s.state['portfolio']
    assert '222222' not in s.state['portfolio']
    assert len(s.state['portfolio']) == MAX_HOLDINGS


def test_position_size_follows_the_weight_constant(tmp_path):
    """종목당 투입은 NAV의 15% — 10%씩 무제한이 아니다."""
    s = _sim(tmp_path)

    s.run([_candidate('111111', '신규A', price=1000)], {})

    pos = s.state['portfolio']['111111']
    assert pos['quantity'] == int(3_000_000 * POSITION_WEIGHT / 1000)


def test_full_slots_leave_cash_headroom(tmp_path):
    """슬롯을 다 채워도 현금이 남아야 한다(버퍼)."""
    s = _sim(tmp_path)
    cands = [_candidate(f'11111{i}', f'신규{i}', price=1000) for i in range(MAX_HOLDINGS + 1)]

    s.run(cands, {})

    assert len(s.state['portfolio']) == MAX_HOLDINGS
    # 버퍼 = 1 - MAX_HOLDINGS × POSITION_WEIGHT. 상수에서 끌어온다.
    buffer_ratio = 1 - MAX_HOLDINGS * POSITION_WEIGHT
    assert s.state['cash'] > 3_000_000 * buffer_ratio * 0.9


def test_same_cycle_sells_do_not_inflate_the_free_slots(tmp_path):
    """같은 사이클에서 청산이 나도 상한을 넘겨 사지 않는다.

    `sell()`은 `state['portfolio']`에서 종목을 지운다. 그래서 잔여 보유는
    `len(portfolio)`만으로 이미 맞는데, 여기서 `sold_today`를 한 번 더 빼면
    청산된 종목이 두 번 세어져 빈 슬롯이 부풀려진다 — 2종목을 손절한 사이클에서
    상한 5개인 심이 7종목을 들고 끝난다. 사이징이 NAV×19%×5=95%라
    초과 매수는 현금을 말리고, 그 다음 신호부터 `buy()`가 조용히 False가 된다
    (2026-08-03에 심2가 거래 0건이던 바로 그 고장).
    """
    held = {f'00000{i}': _holding(f'00000{i}') for i in range(1, MAX_HOLDINGS + 1)}
    s = _sim(tmp_path, portfolio=held)
    prices = {c: 1000 for c in held}
    prices['000001'] = 900   # -10% → 하드 손절
    prices['000002'] = 900

    s.run([_candidate(f'11111{i}', f'신규{i}') for i in range(MAX_HOLDINGS + 1)], prices)

    assert len(s.state['portfolio']) <= MAX_HOLDINGS


def test_timestop_frees_a_slot_that_no_other_exit_would(tmp_path):
    """횡보로 묶인 보유는 타임스톱이 슬롯을 돌려준다.

    심2의 청산은 하드손절(-7%)·트레일링(+5% 활성)·외인 이탈뿐이라, 매입가
    근처에서 오래 횡보하면 어느 갈래도 발화하지 않는다. 2026-09-15 실측:
    보유 5종목이 09-04부터 11일간 -4.35%~+4.00% 안에 갇혀 손절선(-7%)에도
    트레일링 활성선(+5%)에도 닿지 않았고, 그 사이 매수는 0건이었다.
    """
    old = get_kst_now().date() - timedelta(days=TIMEOUT_DAYS + 1)
    held = {'000001': _holding('000001', entry_date=old.strftime('%Y-%m-%d'))}
    s = _sim(tmp_path, portfolio=held)

    s.run([], {'000001': 1000})   # 매입가 그대로 — 다른 청산은 전부 미발화

    assert '000001' not in s.state['portfolio']


def test_timestop_leaves_a_fresh_holding_alone(tmp_path):
    """갓 산 보유는 타임스톱이 건드리지 않는다."""
    held = {'000001': _holding('000001')}
    s = _sim(tmp_path, portfolio=held)

    s.run([], {'000001': 1000})

    assert '000001' in s.state['portfolio']
