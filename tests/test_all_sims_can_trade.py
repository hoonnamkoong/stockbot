"""완벽한 후보를 줘도 못 사는 심이 있는지 잠근다.

전략 신호가 없어서 안 사는 것과, **구조 때문에 어떤 후보를 줘도 못 사는 것**은
다르다. 후자는 배포된 채 영원히 0건이 되고, 로그에는 "주문 없음"으로만 보인다.

실제로 그렇게 된 적이 있다:
  - 심5(레인지)는 버즈 후보(급등주)를 받아 "박스권 저점 매수"가 구조적으로
    불가능했다. 2026-08-14 실측: 저점에 가장 가까운 종목조차 저점 대비 +24%,
    기준은 +3% 이내. 유니버스를 시총 상위(중립)로 바꿔 풀었다.
  - 심4-1은 체결강도 게이트가 유니버스에 없는 필드를 요구해 전 종목이 막혔다.

각 심은 **전략이 다르므로 요구 입력도 다르다** — 상승 모멘텀 후보가 동시에
박스권 저점일 수는 없다. 그래서 하나의 후보를 돌려쓰지 않고 심별로 맞춘다.
여기서 실패하면 "그 심은 어떤 시장에서도 못 산다"는 뜻이다.

사이징(MAX_HOLDINGS × POSITION_WEIGHT)도 함께 확인된다 — 상수를 참조하므로
값을 바꿔도 이 파일은 깨지지 않는다.
"""
import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest

NAV = 3_000_000
BIG_AMOUNT = 50_000_000_000
# ADX가 20~60에 들도록 지그재그. 완전 단조 상승은 ADX 100이라 상한(60)에 걸린다.
ZIGZAG = [1000, 1080, 1000, 1080, 1120]
# 박스권: 저점 900 / 고점 1100 (폭 22% >= 8%)
BOX = [900, 1100, 950, 1080, 900, 1100, 960, 1050, 900,
       1100, 940, 1090, 900, 1100, 930, 1070, 900, 1100, 920]


def _view(cash=NAV):
    return {'nav': NAV, 'cash': cash, 'portfolio': {}, 'cooldown_codes': {}}


def _buys(orders):
    return [o for o in orders if o['action'] == 'BUY']


# ── 심4-1 단타 / 심4 모멘텀 ──────────────────────────────────────────

def _momentum(i):
    return {'code': f'{i:06d}', 'name': f'모멘텀{i}', 'price': 1000,
            'amount': BIG_AMOUNT, 'sparkline_price': list(ZIGZAG),
            'change_rate': '+3.00%', 'tick_power': 180.0,
            'orgn_fake_ntby_qty': 100_000, 'frgn_fake_ntby_qty': 100_000}


def test_sim4_1_daytrade_can_buy():
    from src.strategy.simulators.sim4_bull_daytrading import (
        MAX_HOLDINGS, POSITION_WEIGHT, decide_bull_daytrade,
    )
    cands = [_momentum(i) for i in range(MAX_HOLDINGS + 3)]

    b = _buys(decide_bull_daytrade(_view(), cands, {}))

    assert len(b) == MAX_HOLDINGS
    assert b[0]['quantity'] == int(NAV * POSITION_WEIGHT / 1000)


# ── 심5 레인지 (박스권 저점) ─────────────────────────────────────────

def _box(i):
    return {'code': f'{i:06d}', 'name': f'박스{i}', 'price': 920,
            'amount': BIG_AMOUNT, 'range_history': list(BOX),
            'change_rate': '+0.50%'}


def test_sim5_range_can_buy():
    """이 심이 2026-08-14까지 구조적으로 못 사던 자리다."""
    from src.strategy.simulators.sim5_sideways_swing import (
        MAX_HOLDINGS, POSITION_WEIGHT, decide_sideways,
    )
    cands = [_box(i) for i in range(MAX_HOLDINGS + 3)]

    b = _buys(decide_sideways(_view(), cands, {c['code']: 920 for c in cands}))

    assert len(b) == MAX_HOLDINGS
    assert b[0]['quantity'] == int(NAV * POSITION_WEIGHT / 920)


# ── 심6 인버스 (1종목 특례) ──────────────────────────────────────────

def test_sim6_inverse_can_buy():
    from src.strategy.simulators.sim6_bear_hedge import (
        INVERSE_UNIVERSE, MAX_HOLDINGS, decide_sim6,
    )
    inv = dict(INVERSE_UNIVERSE[0])
    inv.update(price=1200, sparkline_price=[1000, 1050, 1100, 1150, 1200],
               change_rate='+2.00%')

    b = _buys(decide_sim6(_view(), [inv], {inv['code']: 1200}))

    assert len(b) == MAX_HOLDINGS == 1, '인버스는 1종목 특례다'


# ── 심1 심리 (버즈) ──────────────────────────────────────────────────

_WORDS = ['실적', '수주', '신제품', '흑자', '증설', '계약', '수출', '특허']


def _buzz(i, hot=False, rng=None):
    rng = rng or random.Random(7)
    n = 300 if hot else 25
    # 제목이 같으면 도배(spam)로 걸린다. 1인 1글이어야 posts_per_poster가 1이다.
    posts = [{'title': f'{rng.choice(_WORDS)} {rng.randint(1, 9999)} 소식 {j}',
              'likes': rng.randint(1, 50)} for j in range(n)]
    return {'code': f'{i:06d}', 'name': f'버즈{i}', 'price': 1000,
            'amount': BIG_AMOUNT, 'sparkline_price': [980, 1000, 985, 1000, 1000],
            'change_rate': '+0.80%',            # 아직 안 오른 상태여야 산다
            'tick_power': 180.0, 'sentiment': '긍정',
            'frgn_fake_ntby_qty': 50_000, 'orgn_fake_ntby_qty': 50_000,
            'posts': posts, 'recent_posts_count': n, 'unique_posters': n,
            'total_likes': sum(p['likes'] for p in posts),
            'buzz_ratio': 6.0 if hot else 1.0}


def test_sim1_psych_can_buy():
    """버즈는 후보 간 **상대 비교**(z-score)라 표본이 필요하다.
    전부 똑같으면 z가 0이라 아무도 안 튄다."""
    from src.strategy.simulators.sim1_psych import MIN_SAMPLE, POSITION_WEIGHT, decide_psych
    rng = random.Random(7)
    cands = [_buzz(i, rng=rng) for i in range(MIN_SAMPLE + 4)] + [_buzz(99, hot=True, rng=rng)]

    orders, _diags, _snap = decide_psych(_view(), cands, {c['code']: 1000 for c in cands})
    b = _buys(orders)

    assert len(b) == 1, '버즈가 튀는 한 종목만 사야 한다'
    assert b[0]['quantity'] == int(NAV * POSITION_WEIGHT / 1000)


# ── 심2 수급 / 심3 가치 / 심7 리포트 ─────────────────────────────────

def _sim(cls, tmp_path):
    os.environ['SIM_STATE_DIR'] = str(tmp_path)
    s = cls(initial_cash=NAV)
    s.save_state = lambda *a, **k: None
    s.state['cash'] = NAV
    s.state['portfolio'] = {}
    return s


def test_sim2_spillover_can_buy(tmp_path):
    from src.strategy.simulators.sim2_spillover import MAX_HOLDINGS, SectorSpilloverSimulator
    s = _sim(SectorSpilloverSimulator, tmp_path)
    cands = [{'code': f'{i:06d}', 'name': f'수급{i}', 'price': 1000, 'amount': BIG_AMOUNT,
              'change_rate': '+1.50%', 'frgn_fake_ntby_qty': 100_000,
              'orgn_fake_ntby_qty': 100_000, 'foreign_change': 1.5,
              'sparkline_price': [900, 950, 1000, 1020, 1000]}
             for i in range(MAX_HOLDINGS + 3)]

    s.run(cands, {c['code']: 1000 for c in cands})

    assert len(s.state['portfolio']) == MAX_HOLDINGS


def test_sim3_value_can_buy(tmp_path):
    from src.strategy.simulators.sim3_risk import SmartRiskSimulator
    s = _sim(SmartRiskSimulator, tmp_path)
    # per/pbr이 아니라 **per_ttm/pbr_ttm**을 준다. 2026-08-17에 심3의 밸류에이션
    # 기준을 연간 결산 → TTM으로 바꿨다(연간 기준은 실적 개선주를 비싸게 보이게 해
    # 저평가 필터가 반대로 작동했다). 후보에 TTM이 없으면 심3이 KIS를 조회하는데,
    # 테스트에서 네트워크를 타면 안 되므로 여기서 주입한다.
    cands = [{'code': f'{i:06d}', 'name': f'가치{i}', 'price': 1000,
              'amount': 50_000_000_000, 'per_ttm': 5.0, 'pbr_ttm': 0.5,
              'sector_name': '반도체', 'sparkline_price': list(ZIGZAG)}
             for i in range(s.MAX_HOLDINGS + 3)]

    s.run(cands, {c['code']: 1000 for c in cands})

    assert len(s.state['portfolio']) == s.MAX_HOLDINGS


# ── 심10 오케스트레이터 (국면별 위임) ────────────────────────────────

@pytest.mark.parametrize('regime, maker', [('SIDEWAYS', _box), ('BULL', _momentum)])
def test_sim10_can_buy_in_each_regime(tmp_path, regime, maker):
    """심10은 자체 진입 로직이 없다 — 국면에 따라 하위 전략을 그대로 부른다.
    그래서 하위 전략이 막히면 심10도 같이 막힌다(8월 0건이 그랬다)."""
    from src.strategy.simulators.sim10_orchestrator import Sim10OrchestratorSimulator
    s = _sim(Sim10OrchestratorSimulator, tmp_path)
    s._read_regime = lambda: (regime, 70.0)
    cands = [maker(i) for i in range(8)]

    s.run(cands, {c['code']: c['price'] for c in cands})

    assert s.state['portfolio'], f'{regime} 국면에서 한 종목도 못 샀다'
