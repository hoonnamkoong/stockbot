"""Sim1 개조 — 실패 원인이 가설이 아니라 구현이었음을 코드로 못 박는다.

백테스트 69거래·승률 36.4%·순수익 +0.11%(수수료가 이익의 85%). 원인 3가지:
  · `or buzz_count>=500`이 소형주를 하나도 더 잡지 못하고 평상시 대형주만 통과
  · is_price_stable이 -5~+7%로 완화돼 '가격 정체' 가설이 희석
  · 도배(한 사람이 여러 글)를 안 걸렀다
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators.sim1_psych import (
    decide_psych, MAX_HOLDINGS, MIN_SAMPLE, POSITION_WEIGHT,
)


def _own_hist(closes):
    """후보 자신이 들고 오는 날짜 붙은 직전 종가. 날짜는 항상 과거라 오늘 판정과 무관하다."""
    return [{'date': f'200001{i:02d}', 'close': c} for i, c in enumerate(closes, 1)]


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
             'price_history': _own_hist([980, 990, 1000, 1005]), 'tick_power': 130.0,
             'posts': []} for i in range(n)]


def _target(**kw):
    """기본값 = 진입 조건 충족 (관심 폭발 + 가격 정체 + 도배 아님)"""
    s = {'code': 'T001', 'name': '심리주', 'price': 1000, 'amount': 5_000_000_000,
         'recent_posts_count': 300, 'avg_posts': 50,      # 배수 6.0x
         'unique_posters': 200, 'total_likes': 600,       # 글/사람 1.5
         'change_rate': '+1.00%',
         'price_history': _own_hist([900, 940, 970, 990]),   # 우상향 + 현재가 1000 = ADX 100(문턱 15)
         'tick_power': 130.0, 'fact_score': 0.5,
         'posts': [{'title': '3분기 공시 확인'}]}
    s.update(kw)
    return s


def _target_no_spark(**kw):
    """후보 자신은 이력이 없다 — 이력은 view로만 받는 진입 후보."""
    s = _target(**kw)
    s.pop('price_history')
    return s


def _filler_no_spark():
    out = _filler()
    for s in out:
        s.pop('price_history')
    return out


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
def test_position_size_follows_the_weight_constant():
    orders, _, _ = decide_psych(_view(), [_target()] + _filler(), {'T001': 1000})
    # 상수를 참조한다 — 하드코딩하면 사이징을 조정할 때마다 이 테스트가
    # '무엇이 깨졌는지'가 아니라 '숫자가 바뀌었다'만 알려준다.
    assert _buys(orders)[0]['quantity'] == int(3_000_000 * POSITION_WEIGHT / 1000)


def test_max_holdings_is_capped():
    """이전에는 보유 상한이 없어 Sim1만 통일에서 빠져 있었다."""
    cands = [_target(code=f'T{i:03d}', name=f'심리{i}') for i in range(9)] + _filler()
    orders, diags, _ = decide_psych(_view(), cands, {})
    assert len(_buys(orders)) == MAX_HOLDINGS
    assert any(d['reason'] == 'full' for d in diags)


# ── 청산 ────────────────────────────────────────────────
def _held(avg=1000, peak=None):
    return {'T001': {'name': '심리주', 'quantity': 10, 'avg_price': avg,
                     'peak_price': peak if peak is not None else avg}}


TODAY = '20261128'


def _hist_rows(code, closes):
    """날짜가 붙은 이력 계약({code: [{date, close}]}). 마지막 행이 TODAY 직전이 되게 만든다."""
    n = len(closes)
    return {code: [{'date': f'202611{20 + i:02d}', 'close': c} for i, c in enumerate(closes)][:n]}


def test_trailing_stop():
    orders, _, _ = decide_psych(_view(_held(peak=1100)), [], {'T001': 1060})
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '트레일링' in sells[0]['reason']


def test_atr_take_profit():
    cand = [_target_no_spark(price=1200)]
    v = _view(_held())
    v['price_history'] = _hist_rows('T001', [900, 940, 970, 990, 1000])
    orders, _, _ = decide_psych(v, cand, {'T001': 1200}, today=TODAY)
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '목표가' in sells[0]['reason']


def test_atr_stop_loss():
    cand = [_target_no_spark(price=900)]
    v = _view(_held())
    v['price_history'] = _hist_rows('T001', [900, 940, 970, 990, 1000])
    orders, _, _ = decide_psych(v, cand, {'T001': 900}, today=TODAY)
    sells = [o for o in orders if o['action'] == 'SELL']
    assert len(sells) == 1 and '손절' in sells[0]['reason']


# ── 버즈 기준선: 없으면 지어내지 않는다 (2026-11-24) ──────────────────
# 이 파일의 픽스처는 전부 `avg_posts`를 손으로 넣어준다. 프로덕션 입력에는
# 그 키가 없었다 — trade_engine._enrich_universe가 `sparkline_price`는 채우는데
# 게시글 이력을 채우는 줄이 없고, 유일한 생산자(notifier._aggregate_multi_day)는
# 심 입력 경로가 아니다. 그래서 `or 1` 폴백이 매번 걸려 buzz_ratio == posts가
# 됐고(라이브 diag 37,032행 100%), '평상시 대비 2.2배'가 '글 2.2개 이상'으로
# 무력화됐다. 남은 절대 개수 조건은 대형주 필터라 진입 18건 중 12건이
# 삼성전자였고, 리셋 후 5건은 전부 삼성전자·전부 손절·0/5였다.
# 아래 두 테스트는 **프로덕션 입력 모양**(그 키가 없는 dict)을 쓴다.

def test_missing_avg_posts_is_fail_closed():
    s = _target()
    del s['avg_posts']
    orders, diags, _ = decide_psych(_view(), [s] + _filler(), {'T001': 1000})
    assert _buys(orders) == []
    assert _reason(diags, 'T001') == 'no_buzz_baseline'


def test_zero_avg_posts_is_fail_closed():
    """0은 '관심이 없었다'가 아니라 '못 쟀다'다 — 나누면 비율이 무한이 된다."""
    orders, diags, _ = decide_psych(_view(), [_target(avg_posts=0)] + _filler(),
                                    {'T001': 1000})
    assert _buys(orders) == []
    assert _reason(diags, 'T001') == 'no_buzz_baseline'


def test_diag_leaves_buzz_ratio_blank_when_unmeasurable():
    """측정 불가와 값을 같은 칸에 적지 않는다 — 0으로 적으면 두 갈래가 합쳐진다."""
    s = _target()
    del s['avg_posts']
    _, diags, _ = decide_psych(_view(), [s] + _filler(), {'T001': 1000})
    row = next(d for d in diags if d['code'] == 'T001')
    assert row['buzz_ratio'] == ''
    assert row['avg_posts'] == ''


# ── ATR 청산: 상수로 메우지 않는다 ───────────────────────────────
# 보유 종목이 그날 후보 목록에 없으면 sparkline이 비어 `avg * 0.015`가 ATR을
# 대신했다 — 익절 +4.5%·손절 -2.25%의 고정 비율이 하필 손실 종목에서 걸렸다.

def _sells(o):
    return [x for x in o if x['action'] == 'SELL']


def test_no_atr_exit_without_history():
    """이력이 없으면 ATR 익절·손절을 내지 않는다 — 상수로 메우지 않는다."""
    orders, _, _ = decide_psych(_view(_held()), [], {'T001': 950}, today=TODAY)  # 진입가 -5%
    assert _sells(orders) == []
    orders, _, _ = decide_psych(_view(_held()), [], {'T001': 1060}, today=TODAY)  # +6%
    assert _sells(orders) == []


def test_trailing_stop_still_fires_without_history():
    """적응형을 못 하는 것과 손실을 방치하는 것은 다른 문제다. (심1에는 하드 손절이 없고
    이 테스트가 확인하는 것은 트레일링뿐이다.)"""
    orders, _, _ = decide_psych(_view(_held(peak=1100)), [], {'T001': 1060}, today=TODAY)
    sells = _sells(orders)
    assert len(sells) == 1 and '트레일링' in sells[0]['reason']


def test_atr_exit_uses_supplied_history():
    """후보에는 없고 view['price_history']만 있어도 ATR 청산이 난다."""
    v = _view(_held())
    # ATR 2 -> 손절선 997. 상수(1.5%)였다면 977.5라 -1%에서는 안 팔렸을 것이다.
    v['price_history'] = _hist_rows('T001', [1000, 1002, 1000, 1002, 1000])
    orders, _, _ = decide_psych(v, [], {'T001': 990}, today=TODAY)
    sells = _sells(orders)
    assert len(sells) == 1 and '손절' in sells[0]['reason']


def test_atr_differs_by_stock():
    """같은 진입가·같은 현재가(-1%)인데 변동성이 다르면 손절 판정이 갈린다. 상수였다면 같다."""
    port = {'CALM': {'name': 'c', 'quantity': 10, 'avg_price': 1000, 'peak_price': 1000},
            'WILD': {'name': 'w', 'quantity': 10, 'avg_price': 1000, 'peak_price': 1000}}
    v = _view(port)
    v['price_history'] = {
        **_hist_rows('CALM', [1000, 1002, 1000, 1002, 1000]),   # ATR 2 -> 손절선 997
        **_hist_rows('WILD', [1000, 1060, 1000, 1060, 1000]),   # ATR 60 -> 손절선 910
    }
    orders, _, _ = decide_psych(v, [], {'CALM': 990, 'WILD': 990}, today=TODAY)
    assert {o['code'] for o in _sells(orders)} == {'CALM'}


def test_atr_exit_works_when_today_is_omitted():
    """today 인자가 비어도 ATR 청산은 판정된다 — 인자 누락은 '측정 불가'가 아니다."""
    v = _view(_held())
    v['price_history'] = {'T001': [{'date': f'200001{i:02d}', 'close': c}
                                   for i, c in enumerate([1000, 1002, 1000, 1002, 1000], 1)]}
    orders, _, _ = decide_psych(v, [], {'T001': 990})
    sells = _sells(orders)
    assert len(sells) == 1 and '손절' in sells[0]['reason']


# ── 진입 ADX: 이력 계약 ─────────────────────────────────────
# 픽스처 여유(ADX_MIN=15.0): 통과용 [900,940,970,990]+현재가 1000은 방향 100/변동 100이라
# ADX 100.0 -> 문턱에서 85 위. 경계값에 얹지 않는다.
def _entry_view(code, closes):
    v = _view()
    v['price_history'] = _hist_rows(code, closes)
    return v


def test_entry_adx_input_is_prior_four_plus_current(monkeypatch):
    """진입은 당일을 살린다 — spy로 calculate_adx 인자를 정확히 단언한다."""
    from src.strategy.simulators.base_simulator import BaseSimulator
    seen = []
    real = BaseSimulator.calculate_adx

    def spy(closes):
        seen.append(list(closes))
        return real(closes)
    monkeypatch.setattr(BaseSimulator, 'calculate_adx', staticmethod(spy))
    v = _entry_view('T001', [900, 940, 970, 990])
    orders, diags, _ = decide_psych(v, [_target_no_spark()] + _filler_no_spark(),
                                    {'T001': 1000}, today=TODAY)
    assert [900, 940, 970, 990, 1000] in seen
    assert [o['code'] for o in _buys(orders)] == ['T001']
    assert next(d['adx'] for d in diags if d['code'] == 'T001') == '100.0'


def test_entry_without_history_is_no_history_not_weak_adx():
    """지어낸 0.0이 ADX_MIN 비교에 닿지 않는다. 결손 사유가 전략 탈락과 분리된다."""
    orders, diags, _ = decide_psych(_view(), [_target_no_spark()] + _filler_no_spark(),
                                    {'T001': 1000}, today=TODAY)
    assert _buys(orders) == []
    assert _reason(diags, 'T001') == 'no_history'
    # 진단 행에도 0.0을 적지 않는다 — 못 잰 값은 빈 칸이다.
    assert next(d['adx'] for d in diags if d['code'] == 'T001') == ''


def test_entry_with_three_prior_closes_is_no_history():
    """지금은 3개로도 ADX를 계산한다. 바뀐 뒤에는 결손이다(의도된 강화)."""
    v = _entry_view('T001', [940, 970, 990])
    orders, diags, _ = decide_psych(v, [_target_no_spark()] + _filler_no_spark(),
                                    {'T001': 1000}, today=TODAY)
    assert _buys(orders) == []
    assert _reason(diags, 'T001') == 'no_history'
    assert next(d['adx'] for d in diags if d['code'] == 'T001') == ''
