"""Sim12(국면이원 반등/추세형) — decide_sim12 순수함수.

BULL 국면=모멘텀 지속형(이미 오르는 종목 순추세), SIDEWAYS/BEAR=급락반등형(5일
급락 + 거래대금 유지 + 기관 20일 순매수). 2026-08-20 KOSPI 규칙마이닝 실측:
'최고수익 종목 프로파일'이 국면에 따라 정반대였다(강세장 4월엔 모멘텀 지속형이,
약세~횡보 7~8월엔 급락반등형이 대박 패턴)."""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy.simulators.sim12_regime_dual import decide_sim12


def _view(portfolio=None, cash=3_000_000, nav=3_000_000):
    return {'portfolio': portfolio or {}, 'cash': cash, 'initial_cash': 3_000_000,
            'nav': nav, 'cooldown_codes': {}}


def _pos(avg, qty=10, playbook=None, entry_date=None, peak=None):
    p = {'name': 'T', 'quantity': qty, 'avg_price': avg, 'peak_price': peak if peak is not None else avg,
         'entry_date': entry_date or date.today().isoformat(), 'is_scaled_out': False}
    if playbook is not None:
        p['playbook'] = playbook
    return p


def _bull_candidate(code='111111', price=1300):
    """20일치 range_history: 앞 10일은 1000 횡보, 뒤 10일은 1000→1090으로 상승
    (10일 period_chg = (1090-1000)/1000 = +9.0% >= 임계 8.0%). 20일 평균은 1022.5라
    오늘 price=1300과 비교하면 MA20 이격 +27.1% >= 임계 5.0%(둘 다 여유 있게 통과)."""
    hist = [1000] * 10 + [1000, 1010, 1020, 1030, 1040, 1050, 1060, 1070, 1080, 1090]
    return {'code': code, 'name': '상승모멘텀', 'price': price, 'amount': 5_000_000_000,
            'amount_ma20': 4_000_000_000, 'change_rate': '+2.0%',
            'range_history': hist, 'orgn_net_20d': 1.0, 'frgn_net_20d': 1.0,
            'per': 15.0}


def _pb2_candidate(code='222222', price=940):
    """5일 전(hist[-6]) 대비 급락(hist[-1]=940이 5일전보다 -10%대), 거래대금 유지,
    기관 20일 순매수."""
    hist = [1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000,
            1000, 1000, 1000, 1000, 1046, 1000, 970, 960, 950, 940]
    return {'code': code, 'name': '급락반등', 'price': price, 'amount': 4_500_000_000,
            'amount_ma20': 4_000_000_000, 'change_rate': '-1.0%',
            'range_history': hist, 'orgn_net_20d': 2.0, 'frgn_net_20d': 0.5,
            'per': 10.0}


# ── 회피 게이트 ──────────────────────────────────────────────────────

def test_avoids_entry_when_amount_dried_up():
    cand = _bull_candidate()
    cand['amount_ma20'] = cand['amount']  # 비율 1.0으로 만들고
    cand['amount'] = cand['amount_ma20'] * 0.5  # 거래대금이 20일평균의 절반 → 급감
    funnel = []
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BULL', funnel=funnel)

    assert not [o for o in orders if o['action'] == 'BUY']
    assert any(f['reason'] == 'avoid_amount_dry' for f in funnel)


def test_avoids_entry_when_institutions_sell_and_per_is_high():
    cand = _bull_candidate()
    cand['orgn_net_20d'] = -6.0
    cand['per'] = 50.0
    funnel = []
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BULL', funnel=funnel)

    assert not [o for o in orders if o['action'] == 'BUY']
    assert any(f['reason'] == 'avoid_orgn_sell_high_per' for f in funnel)


def test_institutions_selling_alone_without_high_per_does_not_veto():
    """기관 매도만으로는(고PER이 아니면) 이 조합 게이트가 안 걸린다 — 단독
    orgn_net_20d 회피는 이번 구현 범위 밖(조합 게이트만 넣었다)."""
    cand = _bull_candidate()
    cand['orgn_net_20d'] = -6.0
    cand['per'] = 15.0  # 고PER 아님
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BULL')

    assert [o for o in orders if o['action'] == 'BUY']


def test_avoids_entry_when_foreign_20d_sell_regime():
    cand = _bull_candidate()
    cand['frgn_net_20d'] = -6.0
    funnel = []
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BULL', funnel=funnel)

    assert not [o for o in orders if o['action'] == 'BUY']
    assert any(f['reason'] == 'avoid_frgn_sell_20d' for f in funnel)


def test_avoids_entry_when_foreign_holding_rate_drops():
    cand = _bull_candidate()
    cand['frgn_hold_chg_5d'] = -2.0
    funnel = []
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BULL', funnel=funnel)

    assert not [o for o in orders if o['action'] == 'BUY']
    assert any(f['reason'] == 'avoid_frgn_hold_drop' for f in funnel)


def test_avoids_entry_on_deadcat_bounce():
    """당일 급등(+6%)이지만 10일간은 뚜렷한 하락추세(-16%)였던 경우 — 데드캣 바운스로 보고 회피."""
    hist = [1000] * 9 + [1000, 975, 950, 925, 900, 890, 880, 870, 860, 850, 840]
    cand = {'code': '333333', 'name': '데드캣', 'price': 890, 'amount': 5_000_000_000,
            'amount_ma20': 4_000_000_000, 'change_rate': '+6.0%',
            'range_history': hist, 'per': 15.0}
    funnel = []
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BULL', funnel=funnel)

    assert not [o for o in orders if o['action'] == 'BUY']
    assert any(f['reason'] == 'avoid_deadcat' for f in funnel)


def test_missing_gate_fields_do_not_block_entry():
    """모르는 값은 '회피'로 지어내지 않는다."""
    cand = _bull_candidate()
    del cand['orgn_net_20d']
    del cand['frgn_net_20d']
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BULL')

    assert [o for o in orders if o['action'] == 'BUY']


# ── 플레이북1: BULL(모멘텀 지속형) ───────────────────────────────────

def test_bull_regime_enters_on_momentum_continuation():
    cand = _bull_candidate()
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BULL')

    buys = [o for o in orders if o['action'] == 'BUY']
    assert len(buys) == 1 and buys[0]['playbook'] == 1


def test_bull_regime_skips_on_weak_10day_momentum():
    """10일간 거의 안 오른 종목(모멘텀 확인 실패) — MA20 이격과 무관하게 걸러진다."""
    cand = _bull_candidate(price=1000)
    cand['range_history'] = [1000] * 20  # 10일 변동 0% < 임계 8.0%
    funnel = []
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BULL', funnel=funnel)

    assert not [o for o in orders if o['action'] == 'BUY']
    assert any(f['reason'] == 'pb1_momentum_weak' for f in funnel)


def test_bull_regime_skips_when_price_is_still_below_ma20():
    """10일 모멘텀은 확인되지만(+9%) 현재가가 아직 MA20 위로 뚜렷하게 못 올라온 경우."""
    cand = _bull_candidate(price=1000)  # hist 그대로: 10일 변동 +9.0%, MA20 이격은 약함
    funnel = []
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BULL', funnel=funnel)

    assert not [o for o in orders if o['action'] == 'BUY']
    assert any(f['reason'] == 'pb1_below_ma20' for f in funnel)


def test_sideways_regime_does_not_use_playbook1_entry():
    """BULL 조건을 만족하는 후보라도 SIDEWAYS 국면이면 플레이북1로 안 산다
    (플레이북2 조건은 못 만족하므로 둘 다 안 산다)."""
    cand = _bull_candidate()
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'SIDEWAYS')

    assert not [o for o in orders if o['action'] == 'BUY']


# ── 플레이북2: SIDEWAYS/BEAR(급락반등형) ─────────────────────────────

def test_sideways_regime_enters_on_crash_rebound_with_institutions_buying():
    cand = _pb2_candidate()
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'SIDEWAYS')

    buys = [o for o in orders if o['action'] == 'BUY']
    assert len(buys) == 1 and buys[0]['playbook'] == 2


def test_bear_regime_also_uses_playbook2():
    cand = _pb2_candidate()
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'BEAR')

    assert [o for o in orders if o['action'] == 'BUY']


def test_playbook2_skips_without_institutional_buying():
    cand = _pb2_candidate()
    cand['orgn_net_20d'] = -1.0
    funnel = []
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'SIDEWAYS', funnel=funnel)

    assert not [o for o in orders if o['action'] == 'BUY']
    assert any(f['reason'] == 'pb2_no_inst_buying' for f in funnel)


def test_playbook2_skips_when_liquidity_too_thin():
    """5일 급락 + 거래대금유지 조합 규칙 — 유동성 없으면(하위) 반등 신호가 아니다."""
    cand = _pb2_candidate()
    cand['amount'] = cand['amount_ma20'] * 0.7  # 회피게이트(0.65)는 안 걸리지만 pb2 기준(1.0)엔 미달
    funnel = []
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, 'SIDEWAYS', funnel=funnel)

    assert not [o for o in orders if o['action'] == 'BUY']
    assert any(f['reason'] == 'pb2_thin_liquidity' for f in funnel)


# ── 국면 판정불가 ────────────────────────────────────────────────────

def test_unknown_regime_makes_no_new_entries():
    cand = _bull_candidate()
    orders = decide_sim12(_view(), [cand], {cand['code']: cand['price']}, None)

    assert not [o for o in orders if o['action'] == 'BUY']


# ── 청산 ─────────────────────────────────────────────────────────────

def test_hard_stop_loss_applies_regardless_of_playbook():
    portfolio = {'005930': _pos(avg=1000, playbook=2)}
    orders = decide_sim12(_view(portfolio=portfolio), [], {'005930': 920}, 'SIDEWAYS')

    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '손절' in sells[0]['reason']


def test_playbook2_time_stops_after_five_days_even_at_a_profit():
    old_date = (date.today() - timedelta(days=5)).isoformat()
    portfolio = {'005930': _pos(avg=1000, playbook=2, entry_date=old_date)}
    orders = decide_sim12(_view(portfolio=portfolio), [], {'005930': 1010}, 'SIDEWAYS')

    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '타임스탑' in sells[0]['reason']


def test_playbook1_does_not_time_stop():
    """플레이북1(모멘텀 지속형)은 5일 타임스탑 대상이 아니다 — 추세를 더 태운다."""
    old_date = (date.today() - timedelta(days=10)).isoformat()
    portfolio = {'005930': _pos(avg=1000, playbook=1, entry_date=old_date)}
    orders = decide_sim12(_view(portfolio=portfolio), [], {'005930': 1010}, 'BULL')

    assert not [o for o in orders if o['action'] == 'SELL']


def test_untagged_position_does_not_time_stop():
    """playbook 태그가 없는(레거시/수동) 포지션은 타임스탑 대상이 아니다."""
    old_date = (date.today() - timedelta(days=10)).isoformat()
    portfolio = {'005930': _pos(avg=1000, entry_date=old_date)}
    orders = decide_sim12(_view(portfolio=portfolio), [], {'005930': 1010}, 'SIDEWAYS')

    assert not [o for o in orders if o['action'] == 'SELL']


def test_trailing_stop_triggers_after_activation_and_pullback():
    """고점 1100(+10%)에서 1060으로 빠지면 고점대비 -3.64% → 콜백 3.0% 이상, 매도."""
    portfolio = {'005930': _pos(avg=1000, playbook=1, peak=1100)}
    orders = decide_sim12(_view(portfolio=portfolio), [], {'005930': 1060}, 'BULL')

    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '트레일링' in sells[0]['reason']


def test_trailing_stop_does_not_trigger_before_activation():
    """고점이 아직 +5%(활성화 기준)에 못 미치면 하락해도 트레일링은 안 걸린다."""
    portfolio = {'005930': _pos(avg=1000, playbook=1, peak=1020)}
    orders = decide_sim12(_view(portfolio=portfolio), [], {'005930': 990}, 'BULL')

    assert not [o for o in orders if o['action'] == 'SELL']
