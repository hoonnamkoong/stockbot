"""심2 사이징을 다른 매매심과 맞춘다.

2026-08-03에 심2는 거래가 0건이었다. 원인은 신호가 아니라 현금이었다 —
보유 10종목에 현금 36,234원(NAV의 1.2%)이라 어떤 신호가 와도 base.buy가
현금 부족으로 조용히 False를 반환했다. 심2에만 보유 종목 수 상한이 없고
종목당 NAV/10을 투입해 자금을 100% 소진할 수 있었다.
다른 매매심은 전부 NAV×15% × 최대 6종목 = 90%다.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators.sim2_spillover import SectorSpilloverSimulator


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


def _holding(code, qty=10, price=1000):
    return {'name': code, 'quantity': qty, 'avg_price': price,
            'entry_date': '2026-08-03', 'peak_price': price, 'is_scaled_out': False}


def test_stops_buying_at_six_holdings(tmp_path):
    """보유 6종목이면 신호가 있어도 더 사지 않는다."""
    held = {f'00000{i}': _holding(f'00000{i}') for i in range(1, 7)}
    s = _sim(tmp_path, portfolio=held)
    prices = {c: 1000 for c in held}

    s.run([_candidate('111111', '신규A'), _candidate('222222', '신규B')], prices)

    assert '111111' not in s.state['portfolio']
    assert '222222' not in s.state['portfolio']
    assert len(s.state['portfolio']) == 6


def test_position_size_is_fifteen_percent_of_nav(tmp_path):
    """종목당 투입은 NAV의 15% — 10%씩 무제한이 아니다."""
    s = _sim(tmp_path)

    s.run([_candidate('111111', '신규A', price=1000)], {})

    pos = s.state['portfolio']['111111']
    assert pos['quantity'] == 450  # 3,000,000 × 0.15 / 1,000


def test_six_positions_leave_cash_headroom(tmp_path):
    """6종목을 다 채워도 현금이 남아야 한다(90% 투입)."""
    s = _sim(tmp_path)
    cands = [_candidate(f'11111{i}', f'신규{i}', price=1000) for i in range(6)]

    s.run(cands, {})

    assert len(s.state['portfolio']) == 6
    assert s.state['cash'] > 3_000_000 * 0.08
