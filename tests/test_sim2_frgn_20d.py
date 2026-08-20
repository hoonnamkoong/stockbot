"""2026-08-20 KOSPI 규칙마이닝 반영: 심2(수급동승)에 외인 20일 누적 수급을 얹는다.

- 진입: 오늘 하루만 좋아도 20일 누적이 매도국면(<=-5%)이면 노이즈로 보고 거른다.
- 청산: 20일 누적이 아직 매수국면(>0)이면, 하루짜리 이탈 신호만으로 즉시 청산하지 않는다
  (전환 직후에도 fwd_10d +3.72%·승률62%였다 — 표본 42건, 참고용이라 완전 제거는 아니고
  '더 강한 확인'을 요구하는 정도로만 완화).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

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


def _candidate(code, name, price=1000, frgn_net_20d=None):
    """스코어 60 이상이 확실한 후보(수급 A 40점 + 발산 B 40점)."""
    c = {'code': code, 'name': name, 'price': price, 'amount': 5_000_000_000,
         'change_rate': '+1.00%', 'frgn_fake_ntby_qty': 10_000,
         'orgn_fake_ntby_qty': 10_000}
    if frgn_net_20d is not None:
        c['frgn_net_20d'] = frgn_net_20d
    return c


def _holding(code, qty=10, price=1000):
    return {'name': code, 'quantity': qty, 'avg_price': price,
            'entry_date': '2026-08-03', 'peak_price': price, 'is_scaled_out': False}


# ── 진입 게이트 ──────────────────────────────────────────────────────

def test_sell_regime_blocks_entry_even_with_a_good_daily_signal(tmp_path):
    """오늘 수급 A+B로 80점이 나와도 20일 누적이 매도국면(-5% 이하)이면 안 산다."""
    s = _sim(tmp_path)
    s.run([_candidate('111111', '신규A', frgn_net_20d=-6.0)], {})

    assert '111111' not in s.state['portfolio']


def test_buy_regime_does_not_block_entry(tmp_path):
    """20일 누적이 매수국면이면 기존대로 진입한다."""
    s = _sim(tmp_path)
    s.run([_candidate('111111', '신규A', frgn_net_20d=3.0)], {})

    assert '111111' in s.state['portfolio']


def test_missing_frgn_net_20d_does_not_block_entry(tmp_path):
    """모르는 값은 '매도국면'으로 지어내지 않는다 — 스크래핑 실패 시에도 매매는 계속된다."""
    s = _sim(tmp_path)
    s.run([_candidate('111111', '신규A')], {})  # frgn_net_20d 없음

    assert '111111' in s.state['portfolio']


# ── 청산 완화 ────────────────────────────────────────────────────────

def test_daily_outflow_still_exits_when_20d_is_also_negative(tmp_path):
    """20일 누적도 이미 매도국면이면(레벨 신호 확인됨) 하루짜리 이탈에 즉시 청산한다."""
    held = {'005930': _holding('005930')}
    s = _sim(tmp_path, portfolio=held)
    cand = {'code': '005930', 'foreign_change': -1.0, 'frgn_net_20d': -3.0}

    s.run([cand], {'005930': 1000})

    assert '005930' not in s.state['portfolio']


def test_daily_outflow_does_not_exit_while_20d_is_still_a_buy_regime(tmp_path):
    """20일 누적이 아직 순매수(>0)로 남아있으면 하루짜리 이탈만으로는 즉시 청산하지 않는다
    (트레일링 스탑 등 다른 청산 로직에 맡긴다)."""
    held = {'005930': _holding('005930')}
    s = _sim(tmp_path, portfolio=held)
    cand = {'code': '005930', 'foreign_change': -1.0, 'frgn_net_20d': 2.0}

    s.run([cand], {'005930': 1000})

    assert '005930' in s.state['portfolio']


def test_daily_outflow_still_exits_when_20d_is_unknown(tmp_path):
    """20일 누적을 모르면(스크래핑 실패) 기존 동작(즉시 청산)을 보수적으로 유지한다."""
    held = {'005930': _holding('005930')}
    s = _sim(tmp_path, portfolio=held)
    cand = {'code': '005930', 'foreign_change': -1.0}  # frgn_net_20d 없음

    s.run([cand], {'005930': 1000})

    assert '005930' not in s.state['portfolio']
