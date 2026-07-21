"""
Sim6 인버스 ETF 추세추종 순수함수 단위 테스트 — 네트워크 없음.
실행: PYTHONPATH=. python scratch/test_sim6_inverse.py

계약(하락장 데이터 백테스트로 재튜닝, 2026-07-21):
- 진입: 인버스가 상승(현재가>MA5 + 당일 상승) → 쉬운/빠른 진입(늦으면 고점 못 잡음).
- 청산: 느슨하게 — 트레일링(고점 대비 -10%) / 하드손절(-12%). 타이트 청산은 휩쏘로 수익 유실.
- 청산 후 쿨다운 1일(추세 지속 시 재진입).
- 국면 판단 없음: 인버스 가격 추세만 봄. ★ standalone 알파 없음(국면 게이팅 필요) — Sim0 게이트 전제.
"""
import sys
sys.path.insert(0, '.')
from src.strategy.simulators.sim6_bear_hedge import decide_sim6

results = []


def check(name, cond):
    results.append((name, cond)); print(f"[{'PASS' if cond else 'FAIL'}] {name}")


def view(portfolio=None, cash=3_000_000):
    return {'portfolio': portfolio or {}, 'cash': cash, 'initial_cash': 3_000_000,
            'cooldown_codes': {}, 'market_index_healthy': True}


def etf(price=1100, spark=None, daily='+1.5%', code='114800'):
    return {'code': code, 'name': 'KODEX 인버스', 'price': price, 'amount': 700_000_000_000,
            'change_rate': daily, 'sparkline_price': spark or []}


def buys(o): return [x for x in o if x['action'] == 'BUY']
def sells(o): return [x for x in o if x['action'] == 'SELL']


UP = [1000, 1030, 1050, 1080, 1100]     # 5일 상승추세, MA5=1052, period=+10%
DOWN = [1100, 1080, 1050, 1030, 1000]   # 하락추세, 현재가<MA5
FLAT = [1000, 1002, 999, 1001, 1000]    # 횡보, period≈0

# ── 진입 ──────────────────────────────────────────────
# T1: 인버스 상승추세 + 당일 상승 → BUY
o = decide_sim6(view(), [etf(price=1100, spark=UP, daily='+1.5%')], {'114800': 1100})
check('T1 인버스 상승추세 → BUY', len(buys(o)) == 1)

# T2: 인버스 하락추세(현재가<MA5) → 진입 안 함 (시장 상승 중)
o = decide_sim6(view(), [etf(price=1000, spark=DOWN, daily='-1.5%')], {'114800': 1000})
check('T2 인버스 하락추세 → BUY 0건', len(buys(o)) == 0)

# T3: 횡보(추세 약함) → 진입 안 함
o = decide_sim6(view(), [etf(price=1000, spark=FLAT, daily='+0.1%')], {'114800': 1000})
check('T3 인버스 횡보 → BUY 0건', len(buys(o)) == 0)

# T4: 상승추세지만 당일 하락 → 진입 보류
o = decide_sim6(view(), [etf(price=1100, spark=UP, daily='-0.5%')], {'114800': 1100})
check('T4 당일 하락 → BUY 0건', len(buys(o)) == 0)

# T5: 쿨다운 중 → 진입 안 함
from datetime import date, timedelta
v = view(); v['cooldown_codes'] = {'114800': (date.today() + timedelta(days=1)).isoformat()}
o = decide_sim6(v, [etf(price=1100, spark=UP, daily='+1.5%')], {'114800': 1100})
check('T5 쿨다운 중 → BUY 0건', len(buys(o)) == 0)

# ── 청산 ──────────────────────────────────────────────
def held(avg=1000, peak=None, qty=1000):
    return {'114800': {'avg_price': avg, 'peak_price': peak if peak is not None else avg,
                       'quantity': qty, 'name': 'KODEX 인버스'}}


# T6: 하드손절 -12% (인버스 급락=시장 급반등) → SELL
o = decide_sim6(view(held(avg=1000, peak=1000)), [etf(price=880, spark=DOWN)], {'114800': 880})
check('T6 하드손절 → SELL', len(sells(o)) == 1)

# T7: 트레일링 콜백(고점 1200 대비 -10% → 1080 이하) → SELL
o = decide_sim6(view(held(avg=1000, peak=1200)), [etf(price=1070, spark=UP)], {'114800': 1070})
check('T7 트레일링 콜백 → SELL', len(sells(o)) == 1)

# T8: 상승 지속(고점 1200, 현재 1090, 콜백 미도달) → HOLD (라이딩)
o = decide_sim6(view(held(avg=1000, peak=1200)), [etf(price=1090, spark=UP)], {'114800': 1090})
check('T8 라이딩 지속 → SELL 0건', len(sells(o)) == 0)

# T9: 이미 보유 중 → 중복 매수 안 함
o = decide_sim6(view(held(avg=1000, peak=1100)), [etf(price=1100, spark=UP, daily='+1.5%')], {'114800': 1100})
check('T9 보유 중 → BUY 0건', len(buys(o)) == 0)

# ── run() 국면 게이트 (Sim0 판단 소비) ────────────────────
import os
from src.strategy.simulators.sim6_bear_hedge import BearHedgeSimulator

SCRATCH = os.environ.get('TEMP', '.')


def gated_sim(regime):
    sim = BearHedgeSimulator(3_000_000)
    sim.state_file = os.path.join(SCRATCH, '_t_s6_state.json')
    sim.log_file = os.path.join(SCRATCH, '_t_s6_log.json')
    sim.csv_file = os.path.join(SCRATCH, '_t_s6_hist.csv')
    sim.reset_state()
    sim.save_state = lambda *a, **k: None
    sim._read_regime = lambda: regime
    return sim


UP_ETF = etf(price=1100, spark=UP, daily='+1.5%')

# G1: BEAR + 인버스 상승추세 → 매수 진입
s = gated_sim('BEAR'); s.run([UP_ETF], current_prices={'114800': 1100})
check('G1 BEAR 국면 → 인버스 매수', '114800' in s.state['portfolio'])

# G2: BULL 국면 + 인버스 상승추세 → 매수 안 함(게이트 차단)
s = gated_sim('BULL'); s.run([UP_ETF], current_prices={'114800': 1100})
check('G2 BULL 국면 → 매수 안 함', '114800' not in s.state['portfolio'])

# G3: SIDEWAYS 국면 + 인버스 보유 중 → 국면 이탈 청산
s = gated_sim('SIDEWAYS')
s.state['portfolio'] = {'114800': {'avg_price': 1000, 'peak_price': 1000, 'quantity': 100, 'name': 'KODEX 인버스'}}
s.run([UP_ETF], current_prices={'114800': 1100})
check('G3 비BEAR + 보유 → 전량 청산', '114800' not in s.state['portfolio'])

for _f in ['_t_s6_state.json', '_t_s6_log.json', '_t_s6_hist.csv']:
    _p = os.path.join(SCRATCH, _f)
    if os.path.exists(_p):
        os.remove(_p)

# ── 요약 ──────────────────────────────────────────────
passed = sum(1 for _, c in results if c)
print(f"\n{passed}/{len(results)} PASS")
sys.exit(0 if passed == len(results) else 1)
