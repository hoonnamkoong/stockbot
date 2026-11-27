"""심4-1이 왜 안 사는지를 심 스스로 말하게 만든다.

2026-08-14: 전날 고친 체결강도 게이트는 먹었다 — 유니버스 30종목 중 25~27개가
통과했다. 그런데 실전 계좌는 하루 종일 `sim4_bull_daytrading: 주문 없음`이었다.
어제 고친 건 필요조건이었지 충분조건이 아니었다.

문제는 뒤 게이트 다섯이 **한 `if`로 묶여 있었다는 것**이다:

    if (5.0 <= period_change <= 40.0 and daily_change > 0 and 20.0 <= adx < ADX_MAX
            and _validate_tick(stock, 120.0, outage=tick_outage) and has_inst):

통과하지 못하면 무엇 때문인지 알 수 없다. 이 심은 실전 계좌가 실제로 돌리는
심이라 여기서 못 사면 그날 매매가 통째로 없는데, 로그에는 "주문 없음" 한 줄만
남았다. 조건을 쪼개서 센다 — 추측으로 임계값을 만지기 전에.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy.simulators.sim4_bull_daytrading import decide_bull_daytrade

BIG = 5_000_000_000
# ADX가 20~60 안이어야 한다. 완전 단조 상승은 ADX 100이라 상한(60)에 걸린다 —
# 픽스처를 단조로 만들면 '진입 가능한 종목'을 못 만든다.
# 이력 계약 전환: 직전 4개 종가(이력) + 현재가(112) = 5값. 기간 +12%, ADX 42.9
# (하한 20까지 +22.9, 상한 ADX_MAX 60까지 -17.1).
RISING = [100, 108, 100, 108, 112]


def _view(nav=3_000_000):
    return {'nav': nav, 'portfolio': {}, 'cooldown_codes': {}}


def _stock(**kw):
    s = {'code': '005930', 'name': '테스트', 'price': RISING[-1], 'amount': BIG,
         'price_history': [{'date': f'202011{10 + i:02d}', 'close': c} for i, c in enumerate(RISING[:-1])],
         'change_rate': '+2.00%', 'tick_power': 150.0, 'orgn_fake_ntby_qty': 1000}
    s.update(kw)
    return s


def _run(stocks):
    funnel = []
    orders = decide_bull_daytrade(_view(), stocks, {}, funnel=funnel)
    return orders, funnel


def test_a_qualifying_stock_is_still_bought():
    """조건을 쪼개면서 진입 자체를 깨지 않았는지 먼저 고정한다."""
    orders, _ = _run([_stock()])

    assert [o['action'] for o in orders] == ['BUY']


def test_missing_supply_demand_is_named():
    """기관·외인 순매수가 없으면 여기서 죽는다. 예전엔 한 덩어리라 안 보였다."""
    _, funnel = _run([_stock(orgn_fake_ntby_qty=0, frgn_fake_ntby_qty=0)])

    assert funnel[0]['reason'] == 'no_inst'


def test_daily_down_is_named():
    _, funnel = _run([_stock(change_rate='-1.00%')])

    assert funnel[0]['reason'] == 'daily_down'


def test_tick_power_is_named():
    """체결강도 120 미만. 어제 고친 게이트가 실제로 여기서 걸리는지 본다."""
    _, funnel = _run([_stock(tick_power=50.0)])

    assert funnel[0]['reason'] == 'tick'


def test_period_change_is_named():
    """ADX는 통과하는데 기간 상승률이 상한(40%)을 넘는 경우. 이미 다 오른
    종목을 늦게 타는 걸 막는 조건이라, 여기서 얼마나 걸리는지가 중요하다."""
    # 직전 4개 [100,160,100,160] + 현재가 150: ADX 26.3(하한 +6.3), 기간 +50%(상한 40 초과)
    _, funnel = _run([_stock(price=150, price_history=[
        {'date': f'202011{10 + i:02d}', 'close': c} for i, c in enumerate([100, 160, 100, 160])])])

    assert funnel[0]['reason'] == 'period'
    assert funnel[0]['period'] > 40.0


def test_amount_and_price_gates_are_distinguished():
    """'거래대금 미달'과 '가격을 못 받았다'는 원인이 다르다."""
    _, funnel = _run([_stock(code='A', amount=1),
                      _stock(code='B', price=0)])

    reasons = {f['code']: f['reason'] for f in funnel}
    assert reasons['A'] == 'amount'
    assert reasons['B'] == 'no_price'


def test_funnel_is_optional():
    """백테스트 등 운영 밖 호출은 그대로 돈다."""
    orders = decide_bull_daytrade(_view(), [_stock()], {})

    assert [o['action'] for o in orders] == ['BUY']


# ── 이력 계약 전환(sparkline_price 폐기) ─────────────────────────────────
# 입력이 바뀐다: 예전엔 네이버 일봉 마지막 값(장중엔 전일에 멈춰 있을 수 있다)이 끝이었고,
# 이제는 직전 4개 종가 + **현재가**다. 진입은 현재가에서 체결되므로 의도된 변경이다.
# 픽스처 여유: 통과용 ADX 42.9(하한 20까지 +22.9, 상한 ADX_MAX 60까지 -17.1),
# 기간 +12%(범위 5~40).
from src.strategy.simulators import sim4_bull_daytrading as mod

PRIOR4 = [100, 108, 100, 108]
LIVE = 112


def _hist(closes, start=10):
    return [{'date': f'202011{start + i:02d}', 'close': c} for i, c in enumerate(closes)]


def _cand(**kw):
    s = {'code': '005930', 'name': '테스트', 'price': LIVE, 'amount': BIG,
         'price_history': _hist(PRIOR4), 'change_rate': '+2.00%',
         'tick_power': 150.0, 'orgn_fake_ntby_qty': 1000}
    s.update(kw)
    return s


def _spy(monkeypatch):
    adx_in, period_in = [], []
    real_adx, real_period = mod._adx, mod._period_change
    monkeypatch.setattr(mod, '_adx', lambda v: (adx_in.append(list(v)), real_adx(v))[1])
    monkeypatch.setattr(mod, '_period_change', lambda v: (period_in.append(list(v)), real_period(v))[1])
    return adx_in, period_in


def test_adx_input_is_prior_four_plus_live_price_shared(monkeypatch):
    """ADX·기간 두 소비자가 같은 5값(직전 4종가 + 현재가)을 받는다. 낡은 sparkline은 안 읽는다."""
    monkeypatch.setattr(mod.clock, 'date_compact', lambda *a: '20261128')
    adx_in, period_in = _spy(monkeypatch)
    # 오늘 행(미완성 봉)과 낡은 sparkline을 일부러 섞는다 — 둘 다 입력에 들어오면 안 된다.
    c = _cand(price_history=_hist(PRIOR4) + [{'date': '20261128', 'close': 999}],
              sparkline_price=[1, 2, 3, 4, 5])
    funnel = []
    orders = decide_bull_daytrade(_view(), [c], {}, funnel=funnel)

    assert adx_in == [PRIOR4 + [LIVE]]
    assert period_in == [PRIOR4 + [LIVE]]
    assert [o['action'] for o in orders] == ['BUY']


def test_missing_history_is_named_no_history():
    """이력이 없으면 'no_history'. 'adx_low'(전략 탈락)로 섞이면 안 된다."""
    c = _cand()
    del c['price_history']
    _, funnel = _run([c])

    assert funnel[0]['reason'] == 'no_history'


def test_short_history_is_named_no_history():
    """직전 종가가 3개뿐이면 4개를 지어내지 않는다."""
    _, funnel = _run([_cand(price_history=_hist(PRIOR4[:3]))])

    assert funnel[0]['reason'] == 'no_history'


def test_history_supplied_by_view_is_used(monkeypatch):
    """후보가 이력을 안 들고 있어도 view['price_history'] 공급분을 쓴다."""
    adx_in, _ = _spy(monkeypatch)
    c = _cand()
    del c['price_history']
    view = _view()
    view['price_history'] = {'005930': _hist(PRIOR4)}
    orders = decide_bull_daytrade(view, [c], {})

    assert adx_in == [PRIOR4 + [LIVE]]
    assert [o['action'] for o in orders] == ['BUY']
