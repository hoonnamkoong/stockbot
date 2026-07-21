"""
Sim5 재설계(레인지 저점 진입 + 트레일링 청산) 순수함수 단위 테스트 — 네트워크 없음.
실행: PYTHONPATH=. python scratch/test_sim5_redesign.py

계약:
- 진입: range_history(20일 종가) 기반 채널. 폭>=MIN_WIDTH_PCT, 저점 +LOW_ZONE 이내,
        당일 급락(-2%↓) 아님, 거래대금 하한.
- 청산: 손절(-3%) / 타임스탑(7일) / 트레일링(peak가 채널상단 근접 시 발동, 콜백 2%).
        고정 익절(+4%) 없음 → 승자는 상단 돌파 시 계속 라이딩.
"""
import sys
from datetime import date, timedelta

sys.path.insert(0, '.')
from src.strategy.simulators.sim5_sideways_swing import decide_sideways

results = []


def check(name, cond):
    results.append((name, cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


def view(portfolio=None, cash=3_000_000):
    return {
        'portfolio': portfolio or {},
        'cash': cash,
        'initial_cash': 3_000_000,
        'cooldown_codes': {},
        'market_index_healthy': True,
    }


def stock(code='000001', price=102, rng=None, daily='+0.5%', amount=5_000_000_000):
    return {
        'code': code, 'name': f'종목{code}', 'price': price, 'amount': amount,
        'change_rate': daily, 'range_history': rng or [],
    }


def buys(orders):
    return [o for o in orders if o['action'] == 'BUY']


def sells(orders):
    return [o for o in orders if o['action'] == 'SELL']


WIDE = [100, 108, 103, 112, 105, 115, 101, 110, 104, 113, 102, 111, 106, 114, 100, 109, 105, 112, 103, 110]
# WIDE: low=100, high=115, width=15%

# ── 진입 ──────────────────────────────────────────────
# T1: 넓은 채널 + 저점 근접 + 정상 등락 → 매수
o = decide_sideways(view(), [stock(price=102, rng=WIDE)], {'000001': 102})
check('T1 넓은채널 저점근접 → BUY 1건', len(buys(o)) == 1)

# T2: 좁은 채널(폭 4%) → 수수료 무의미 셋업, 매수 안 함
NARROW = [100, 101, 102, 103, 104, 101, 102, 103, 104, 102, 101, 103, 104, 102, 100, 103, 104, 101, 102, 103]
o = decide_sideways(view(), [stock(price=100, rng=NARROW)], {'000001': 100})
check('T2 좁은채널 → BUY 0건', len(buys(o)) == 0)

# T3: 채널 중단(저점존 밖) → 매수 안 함
o = decide_sideways(view(), [stock(price=110, rng=WIDE)], {'000001': 110})
check('T3 채널중단 → BUY 0건', len(buys(o)) == 0)

# T4: 당일 급락 중(-5%) → 매수 안 함
o = decide_sideways(view(), [stock(price=101, rng=WIDE, daily='-5.0%')], {'000001': 101})
check('T4 당일급락 → BUY 0건', len(buys(o)) == 0)

# T5: 이력 부족(<10) → 매수 안 함
o = decide_sideways(view(), [stock(price=100, rng=[100, 105, 110])], {'000001': 100})
check('T5 이력부족 → BUY 0건', len(buys(o)) == 0)

# ── 청산 ──────────────────────────────────────────────
def held(avg=100, peak=None, entry_days_ago=1):
    return {'000001': {
        'avg_price': avg, 'peak_price': peak if peak is not None else avg,
        'entry_date': (date.today() - timedelta(days=entry_days_ago)).isoformat(),
        'quantity': 100,
    }}


# T6: 하드 손절 -4% → SELL
o = decide_sideways(view(held(avg=100, peak=100)), [stock(price=96, rng=WIDE)], {'000001': 96})
check('T6 손절 → SELL', len(sells(o)) == 1)

# T7: 타임스탑 8일 경과(트레일링 미발동) → SELL
o = decide_sideways(view(held(avg=100, peak=101, entry_days_ago=8)),
                    [stock(price=101, rng=WIDE)], {'000001': 101})
check('T7 타임스탑 → SELL', len(sells(o)) == 1)

# T8: 트레일링 발동(peak 114 상단근접) 후 콜백(현재 111) → SELL
o = decide_sideways(view(held(avg=100, peak=114)), [stock(price=111, rng=WIDE)], {'000001': 111})
check('T8 트레일링 콜백 → SELL', len(sells(o)) == 1)

# T9: 승자 보유(+8%, peak 108 상단 미근접) → 고정익절 없음, HOLD
o = decide_sideways(view(held(avg=100, peak=108)), [stock(price=108, rng=WIDE)], {'000001': 108})
check('T9 승자 라이딩(+8%) → SELL 0건 (고정익절 폐지)', len(sells(o)) == 0)

# T10: 상단 돌파 라이딩(현재 120 > 상단 115, 콜백 미도달) → HOLD
o = decide_sideways(view(held(avg=100, peak=120)), [stock(price=120, rng=WIDE)], {'000001': 120})
check('T10 상단돌파 라이딩 → SELL 0건', len(sells(o)) == 0)

# ── 요약 ──────────────────────────────────────────────
passed = sum(1 for _, c in results if c)
print(f"\n{passed}/{len(results)} PASS")
sys.exit(0 if passed == len(results) else 1)
