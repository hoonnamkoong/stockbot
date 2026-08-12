"""체결강도 게이트는 '수급이 약한 날'과 '못 잰 날'을 구분해야 한다.

2026-08-12: inquire-ccnl 응답을 dict로 잘못 읽어 tick_power가 100% 0이었는데,
게이트가 0을 무조건 면제(통과)로 처리해서 Sim1·Sim4·Sim4-1의 체결강도 조건이
**한 달 넘게 존재하지 않았다.** 알림이 뜨기 전까지 아무도 몰랐고, 방향도 나빴다 —
매수를 막는 쪽이 아니라 더 내보내는 쪽으로 무너졌다(fail-open).

개별 종목의 0은 여전히 면제한다(신규상장·거래정지 등 종목 사정일 수 있다).
런 전체가 0일 때만 '측정이 죽었다'로 보고 차단한다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators.base_simulator import BaseSimulator


def test_zero_tick_power_passes_when_other_stocks_have_values():
    """개별 종목만 0이면 종목 사정이다 — 면제(현행 유지)."""
    assert BaseSimulator.validate_tick_power({'tick_power': 0.0}, outage=False) is True


def test_zero_tick_power_blocked_when_whole_run_is_missing():
    """런 전체가 0이면 '데이터 없음'이 아니라 '측정 불가'다 — 통과시키지 않는다."""
    assert BaseSimulator.validate_tick_power({'tick_power': 0.0}, outage=True) is False


def test_real_value_still_judged_against_threshold_during_outage():
    """전량 결손 판정과 무관하게, 값이 있으면 임계값으로 판단한다."""
    assert BaseSimulator.validate_tick_power({'tick_power': 130.0}, threshold=120.0) is True
    assert BaseSimulator.validate_tick_power({'tick_power': 110.0}, threshold=120.0) is False


def test_outage_detected_when_every_candidate_is_zero():
    candidates = [{'tick_power': 0.0}, {'tick_power': 0.0}, {}]
    assert BaseSimulator.tick_power_outage(candidates) is True


def test_outage_not_detected_when_any_candidate_has_a_value():
    """한 종목이라도 값이 있으면 측정 경로는 살아 있다."""
    candidates = [{'tick_power': 0.0}, {'tick_power': 128.9}]
    assert BaseSimulator.tick_power_outage(candidates) is False


def test_empty_candidates_is_not_an_outage():
    """후보가 없는 것은 측정 실패가 아니다 — 0/0을 장애로 부르면 안 된다."""
    assert BaseSimulator.tick_power_outage([]) is False


# ── 실제 심에 배선됐는가 ────────────────────────────────
# 위 단위 테스트만으로는 부족하다. 08-12 사고의 본질이 "게이트 함수는 멀쩡한데
# 입력이 전부 0이라 무력화됐다"였으므로, 심 수준에서 진입이 실제로 막히는지 본다.

MID_ADX_SPARKLINE = [90, 95, 90, 98, 93, 100]   # ADX≈38.5 — 상·하한 사이


def _view(nav=3_000_000):
    return {'portfolio': {}, 'cash': nav, 'initial_cash': 3_000_000, 'nav': nav,
            'cooldown_codes': {}}


def _cand(code, tick_power):
    return {'code': code, 'name': f'종목{code}', 'price': 1000, 'amount': 5_000_000_000,
            'sparkline_price': MID_ADX_SPARKLINE, 'change_rate': '+3.0%',
            'orgn_fake_ntby_qty': 100, 'frgn_fake_ntby_qty': 0, 'tick_power': tick_power}


def test_sim4_1_does_not_enter_when_every_candidate_lost_tick_power():
    from src.strategy.simulators.sim4_bull_daytrading import decide_bull_daytrade
    cands = [_cand('111', 0.0), _cand('222', 0.0)]
    orders = decide_bull_daytrade(_view(), cands, {'111': 1000, '222': 1000})
    assert not [o for o in orders if o['action'] == 'BUY']


def test_sim4_1_still_exempts_a_single_missing_stock():
    """회귀 방지 — 한 종목만 0인 건 종목 사정이라 계속 면제한다."""
    from src.strategy.simulators.sim4_bull_daytrading import decide_bull_daytrade
    cands = [_cand('111', 0.0), _cand('222', 130.0)]
    orders = decide_bull_daytrade(_view(), cands, {'111': 1000, '222': 1000})
    assert '111' in [o['code'] for o in orders if o['action'] == 'BUY']


def test_sim4_does_not_enter_when_every_candidate_lost_tick_power(tmp_path):
    from src.strategy.simulators.sim4_bull_momentum import BullMomentumSimulator
    nav = 3_000_000
    sim = BullMomentumSimulator(initial_cash=nav)
    sim.state_file = str(tmp_path / "s.json")
    sim.csv_file = str(tmp_path / "s.csv")
    sim.log_file = str(tmp_path / "s.log")
    sim.state = {'initial_cash': nav, 'cash': nav, 'invested': 0, 'portfolio': {},
                 'peak_nav': nav, 'total_fees': 0, 'history': [nav], 'daily_trades': [],
                 'cooldown_codes': {}}
    sim.run([_cand('111', 0.0), _cand('222', 0.0)], {'111': 1000, '222': 1000})
    assert sim.state['portfolio'] == {}
