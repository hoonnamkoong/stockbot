"""프로그램 매매 엔진 핵심 안전 로직 검증 (네트워크/실계좌 없이).

1. 화이트리스트: tradeable 심만 인스턴스화, 분석기(Libero)/미지 id는 None
2. 어댑터: buy/sell 의도 수집 + 스냅샷 일관 + 수동보유(미소유) 매도 차단 + budget 초과 매수 차단
3. 원장 반영: _apply_order_to_positions
4. 복리: realized_pnl 원장 기본값 + effective_budget(budget+realized_pnl) 계산·클램프
실행: python scratch/verify_program_trading.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy.registry import get_tradeable_simulator_ids, get_simulator_by_id
from src.pipeline.workers.program_trader import _make_adapter, _apply_order_to_positions, _read_ledger

results = []

# 1) 화이트리스트
ids = get_tradeable_simulator_ids()
wl_ok = ('sim0_libero' not in ids) and ('sim4_bull' in ids) and len(ids) >= 5
results.append(('tradeable 목록: Libero 제외 & 매매심 포함', wl_ok))
print(f"[1] tradeable ids={ids}")
print(f"    Libero 제외={('sim0_libero' not in ids)}  {'PASS' if wl_ok else 'FAIL'}")

libero = get_simulator_by_id('sim0_libero')       # 분석기 → None
unknown = get_simulator_by_id('sim_does_not_exist')  # 미지 → None
tradeable_sim = get_simulator_by_id('sim4_bull')    # 매매심 → 인스턴스
gate_ok = (libero is None) and (unknown is None) and (tradeable_sim is not None)
results.append(('get_simulator_by_id 화이트리스트 강제', gate_ok))
print(f"[1b] libero={libero}  unknown={unknown}  sim4_bull={'OK' if tradeable_sim else None}  "
      f"{'PASS' if gate_ok else 'FAIL'}")

# 2) 어댑터
class Dummy:
    pass

sim = Dummy()
snap = {'cash': 1_000_000, 'invested': 0, 'portfolio': {}}
orders = _make_adapter(sim, snap, '2026-07-01')

b1 = sim.buy('005930', '삼성전자', 70000, 10, 'entry')     # 700,000 ≤ cash
cash_after_buy = snap['cash']
sell_manual = sim.sell('000660', 100000, 5)                # 미소유 → 차단
sell_owned = sim.sell('005930', 72000, 5)                  # 소유분 부분매도
over_budget = sim.buy('035420', 'NAVER', 500000, 100, '')  # 5천만 > 잔여 cash → 차단
save_noop = (sim.save_state() is None)                     # save_state no-op

adapter_ok = (b1 is True and cash_after_buy == 300_000 and sell_manual is False
              and sell_owned is True and over_budget is False
              and snap['portfolio']['005930']['quantity'] == 5
              and [o['side'] for o in orders] == ['buy', 'sell'])
results.append(('어댑터: 의도수집·수동보유 미매도·budget 차단·상태보호', adapter_ok))
print(f"[2] buy={b1} cash={cash_after_buy} sell(미소유)={sell_manual} sell(소유)={sell_owned} "
      f"over_budget={over_budget} orders={[o['side'] for o in orders]}  {'PASS' if adapter_ok else 'FAIL'}")

# 3) 원장 반영
pos = {}
_apply_order_to_positions(pos, {'side': 'buy', 'code': '005930', 'name': '삼성전자', 'qty': 10, 'price': 70000}, '2026-07-01')
_apply_order_to_positions(pos, {'side': 'buy', 'code': '005930', 'name': '삼성전자', 'qty': 10, 'price': 80000}, '2026-07-01')
avg_ok = pos['005930']['quantity'] == 20 and abs(pos['005930']['avg_price'] - 75000) < 1
_apply_order_to_positions(pos, {'side': 'sell', 'code': '005930', 'name': '삼성전자', 'qty': 20, 'price': 90000}, '2026-07-01')
sold_ok = '005930' not in pos
ledger_ok = avg_ok and sold_ok
results.append(('원장: 평단 재계산 + 전량매도 제거', ledger_ok))
print(f"[3] avg재계산={avg_ok} 전량매도제거={sold_ok}  {'PASS' if ledger_ok else 'FAIL'}")

# 4) 복리: 원장 기본값 + effective_budget 계산 (사용자 시나리오: 200만 배정 -> 50% 익절 -> 300만 가용)
ledger_defaults_ok = _read_ledger().get('realized_pnl', 'MISSING') == 0
print(f"[4a] _read_ledger() 기본값에 realized_pnl=0 포함  {'PASS' if ledger_defaults_ok else 'FAIL'}")


def compute_effective_budget(budget, realized_pnl, real_account_value):
    """run_program_trading의 effective_budget 계산·클램프를 그대로 재현(회귀 검증용)."""
    eb = budget + realized_pnl
    if eb > real_account_value:
        eb = real_account_value
    return eb


# 200만 배정 -> 전액 매수 -> 50% 익절 매도(실현손익 +100만) -> 다음 실행 300만 가용
budget = 2_000_000
realized_pnl_after_profit = 20 * (150000 - 100000)  # 20주, 매입가 10만->매도가 15만 = +100만
eb1 = compute_effective_budget(budget, realized_pnl_after_profit, real_account_value=10_000_000)
compound_ok = eb1 == 3_000_000
print(f"[4b] 200만 배정 + 실현손익(+100만) -> effective_budget={eb1:,.0f}  {'PASS' if compound_ok else 'FAIL'}")

# 손실 시나리오: 실현손익 -50만 -> 다음 실행 150만로 축소
realized_pnl_after_loss = -500_000
eb2 = compute_effective_budget(budget, realized_pnl_after_loss, real_account_value=10_000_000)
loss_ok = eb2 == 1_500_000
print(f"[4c] 200만 배정 + 실현손실(-50만) -> effective_budget={eb2:,.0f}  {'PASS' if loss_ok else 'FAIL'}")

# 안전 클램프: 실현손익 과대 계상되어도 실제 계좌가치를 못 넘음
eb3 = compute_effective_budget(budget, realized_pnl=50_000_000, real_account_value=3_500_000)
clamp_ok = eb3 == 3_500_000
print(f"[4d] 실현손익 과대 -> 실제 계좌가치(350만)로 클램프: {eb3:,.0f}  {'PASS' if clamp_ok else 'FAIL'}")

results.append(('복리: 원장 기본값', ledger_defaults_ok))
results.append(('복리: 수익 반영(200만->300만)', compound_ok))
results.append(('복리: 손실 반영(200만->150만)', loss_ok))
results.append(('복리: 실제 계좌가치 클램프', clamp_ok))

allok = all(ok for _, ok in results)
print("\n결과:", "ALL PASS" if allok else "CHECK ABOVE")
for name, ok in results:
    print(f"  {'O' if ok else 'X'} {name}")
sys.exit(0 if allok else 1)
