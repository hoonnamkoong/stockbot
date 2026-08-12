"""Sim1 개조 — 실패 원인이 가설이 아니라 구현이었음을 코드로 못 박는다.

백테스트 69거래·승률 36.4%·순수익 +0.11%(수수료가 이익의 85%). 원인 3가지:
  · `or buzz_count>=500`이 소형주를 하나도 더 잡지 못하고 평상시 대형주만 통과
  · is_price_stable이 -5~+7%로 완화돼 '가격 정체' 가설이 희석
  · 도배(한 사람이 여러 글)를 안 걸렀다
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators.sim1_psych import decide_psych, MIN_SAMPLE


def _view(portfolio=None, nav=3_000_000):
    return {'portfolio': portfolio or {}, 'cash': nav, 'initial_cash': 3_000_000,
            'nav': nav, 'cooldown_codes': {}}


def _filler(n=MIN_SAMPLE + 2):
    """횡단면 z 표본. 값에 분산을 준다 — 전부 같으면 표준편차가 0이라
    z가 만들어지지 않고, 조금만 다른 종목도 극단값이 돼버린다."""
    return [{'code': f'F{i:03d}', 'name': f'중립{i}', 'price': 1000,
             'amount': 2_000_000_000, 'recent_posts_count': 30 + i * 3,
             'avg_posts': 30 + i * 3, 'unique_posters': 24 + i * 2,
             'total_likes': 30 + i * 3, 'change_rate': '+0.50%',
             'sparkline_price': [980, 990, 1000, 1005, 1000], 'tick_power': 130.0,
             'posts': []} for i in range(n)]


def _target(**kw):
    """기본값 = 진입 조건 충족 (관심 폭발 + 가격 정체 + 도배 아님)"""
    s = {'code': 'T001', 'name': '심리주', 'price': 1000, 'amount': 5_000_000_000,
         'recent_posts_count': 300, 'avg_posts': 50,      # 배수 6.0x
         'unique_posters': 200, 'total_likes': 600,       # 글/사람 1.5
         'change_rate': '+1.00%',
         'sparkline_price': [900, 940, 970, 990, 1000],   # 우상향 = ADX 높음
         'tick_power': 130.0, 'fact_score': 0.5,
         'posts': [{'title': '3분기 공시 확인'}]}
    s.update(kw)
    return s


def _buys(o):
    return [x for x in o if x['action'] == 'BUY']


def _reason(diags, code):
    return next(d['reason'] for d in diags if d['code'] == code)


# ── 진입 ────────────────────────────────────────────────
def test_entry_on_buzz_spike_with_flat_price():
    orders, diags, _ = decide_psych(_view(), [_target()] + _filler(), {'T001': 1000})
    assert [o['code'] for o in _buys(orders)] == ['T001']
    assert _reason(diags, 'T001') == ''


def test_large_cap_constant_buzz_no_longer_enters():
    """`or buzz_count>=500`이 잡던 바로 그 케이스 — 평상시 대형주.
    글은 800개지만 평소에도 800개다(배수 1.0x). 관심 폭발이 아니다."""
    big = _target(recent_posts_count=800, avg_posts=800, unique_posters=600,
                  total_likes=1600)
    orders, diags, _ = decide_psych(_view(), [big] + _filler(), {'T001': 1000})
    assert _buys(orders) == []
    assert _reason(diags, 'T001') == 'buzz'


def test_price_already_moved_is_rejected():
    """'가격 정체'가 가설의 핵심이다. +7%까지 받던 완화를 되돌렸다."""
    orders, diags, _ = decide_psych(_view(), [_target(change_rate='+6.00%')] + _filler(),
                                 {'T001': 1000})
    assert _buys(orders) == []
    assert _reason(diags, 'T001') == 'price_moved'


def test_spam_board_is_rejected():
    """300글을 20명이 썼으면(15글/명) 관심이 아니라 도배다."""
    orders, diags, _ = decide_psych(_view(), [_target(unique_posters=20)] + _filler(),
                                 {'T001': 1000})
    assert _buys(orders) == []
    assert _reason(diags, 'T001') == 'spam'


def test_illiquid_is_rejected():
    orders, diags, _ = decide_psych(_view(), [_target(amount=500_000_000)] + _filler(),
                                 {'T001': 1000})
    assert _buys(orders) == [] and _reason(diags, 'T001') == 'illiquid'


def test_weak_tick_power_is_rejected():
    orders, diags, _ = decide_psych(_view(), [_target(tick_power=90.0)] + _filler(),
                                 {'T001': 1000})
    assert _buys(orders) == [] and _reason(diags, 'T001') == 'weak_demand'


def test_zero_tick_power_is_exempt_when_others_have_values():
    """개별 종목의 0은 종목 사정일 수 있다 — 계속 면제한다(회귀 방지)."""
    orders, _, _ = decide_psych(_view(), [_target(tick_power=0.0)] + _filler(),
                                {'T001': 1000})
    assert [o['code'] for o in _buys(orders)] == ['T001']


def test_run_wide_tick_power_outage_blocks_entry():
    """후보 전체가 0이면 '수급이 약한 날'이 아니라 '못 잰 날'이다 — 진입 금지.

    2026-08-12: inquire-ccnl 응답을 dict로 잘못 읽어 tick_power가 100% 0이었고,
    0을 무조건 면제하던 게이트가 이 조건을 통째로 없앴다.
    """
    cands = [_target(tick_power=0.0)] + [dict(f, tick_power=0.0) for f in _filler()]
    orders, diags, _ = decide_psych(_view(), cands, {'T001': 1000})
    assert _buys(orders) == [] and _reason(diags, 'T001') == 'weak_demand'


# ── 진단 로그 ────────────────────────────────────────────
def test_every_candidate_is_logged():
    """통과한 것만 보면 '왜 이건 걸렀나'를 영영 못 본다."""
    cands = [_target()] + _filler()
    _, diags, _ = decide_psych(_view(), cands, {'T001': 1000})
    assert len(diags) == len(cands)
    assert {d['decision'] for d in diags} == {'entry', 'skip'}


def test_diag_carries_decision_inputs():
    _, diags, _ = decide_psych(_view(), [_target()] + _filler(), {'T001': 1000})
    d = next(x for x in diags if x['code'] == 'T001')
    assert d['buzz_ratio'] == '6.00'
    assert d['posts_per_poster'] == '1.50'
    assert d['likes_per_post'] == '2.00'
    assert d['z_posters'] != '' and d['ignition'] != ''
    assert d['fact_score'] == 0.5


def test_weak_ignition_is_rejected():
    """다른 조건을 다 만족해도 점화가 약하면 안 산다."""
    # 횡단면 중위권이라 z가 거의 0인 종목. 다만 avg_posts가 낮아 관심 배수는 크다.
    low = _target(recent_posts_count=48, avg_posts=12, unique_posters=34, total_likes=48)
    orders, diags, _ = decide_psych(_view(), [low] + _filler(), {'T001': 1000})
    d = next(x for x in diags if x['code'] == 'T001')
    assert abs(float(d['ignition'])) < 2.5
    assert _buys(orders) == [] and d['reason'] == 'weak_ignition'


def test_thin_sample_fails_closed():
    """표본이 얇아 z를 못 내면 통과시키지 않는다.
    '신호 없음'을 '신호 있음'으로 취급하면 안 된다."""
    orders, diags, _ = decide_psych(_view(), [_target()] + _filler(3), {'T001': 1000})
    d = next(x for x in diags if x['code'] == 'T001')
    assert d['z_posters'] == '' and d['ignition'] == ''
    assert _buys(orders) == [] and d['reason'] == 'no_ignition'


# ── 사이징 (전 심 통일) ──────────────────────────────────
def test_position_size_is_fifteen_percent():
    orders, _, _ = decide_psych(_view(), [_target()] + _filler(), {'T001': 1000})
    assert _buys(orders)[0]['quantity'] == int(3_000_000 * 0.15 / 1000)


def test_max_six_holdings():
    """이전에는 보유 상한이 없어 Sim1만 통일에서 빠져 있었다."""
    cands = [_target(code=f'T{i:03d}', name=f'심리{i}') for i in range(9)] + _filler()
    orders, diags, _ = decide_psych(_view(), cands, {})
    assert len(_buys(orders)) == 6
    assert any(d['reason'] == 'full' for d in diags)


# ── 청산 ────────────────────────────────────────────────
def _held(avg=1000, peak=None):
    return {'T001': {'name': '심리주', 'quantity': 10, 'avg_price': avg,
                     'peak_price': peak if peak is not None else avg}}


def test_trailing_stop():
    orders, _, _ = decide_psych(_view(_held(peak=1100)), [], {'T001': 1060})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '트레일링' in sells[0]['reason']


def test_atr_take_profit():
    cand = [_target(price=1200)]
    orders, _, _ = decide_psych(_view(_held()), cand, {'T001': 1200})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '목표가' in sells[0]['reason']


def test_atr_stop_loss():
    cand = [_target(price=900)]
    orders, _, _ = decide_psych(_view(_held()), cand, {'T001': 900})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '손절' in sells[0]['reason']
