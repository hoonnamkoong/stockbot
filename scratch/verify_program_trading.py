"""프로그램 매매 엔진 핵심 안전 로직 검증 (네트워크/실계좌 없이).

1. 화이트리스트: tradeable 심만 인스턴스화, 분석기(Libero)/미지 id는 None
2. 어댑터: buy/sell 의도 수집 + 스냅샷 일관 + 수동보유(미소유) 매도 차단 + budget 초과 매수 차단
   + [신규] 실계좌 보유·원장 부재 종목 매수 거부(원장 유실/수동 보유 이중 방어)
3. 원장 반영: _apply_order_to_positions
4. 복리: realized_pnl 원장 기본값 + effective_budget(budget+realized_pnl) 계산·클램프
5. [신규] 원장 GitHub API I/O: 404 부트스트랩 / 조회 실패 fail-closed / sha 충돌 재시도
6. [신규] 사이징 budget 연동: get_simulator_by_id(initial_cash=...)
7. [신규] 심 전용 유니버스 적용(_resolve_candidates): universe/enrich/fallback 경로
8. [신규] 전략 플래그 머지(_merge_strategy_flags): partial_sold 보존, 실패 종목 제외
9. [신규] Sim4-1 통합: 진흥기업 -22% 시나리오 → 손절 매도 + 쿨다운 기록 (실사고 재현)
실행: python scratch/verify_program_trading.py
"""
import os
import sys
import json
import base64

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy.registry import get_tradeable_simulator_ids, get_simulator_by_id
import src.pipeline.workers.program_trader as pt
from src.pipeline.workers.program_trader import (
    _make_adapter, _apply_order_to_positions, _default_ledger,
    _read_ledger_fresh, _write_ledger, _resolve_candidates, _merge_strategy_flags,
)

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

# 2b) [신규] 실잔고 이중 방어: 실계좌에 있는데 원장(스냅샷)에 없는 종목 매수 거부
sim2 = Dummy()
snap2 = {'cash': 2_000_000, 'invested': 0,
         'portfolio': {'065170': {'name': '비엘팜텍', 'quantity': 72, 'avg_price': 4110}}}
real_holdings = {'002780': {'qty': 1230}, '065170': {'qty': 72}, '272210': {'qty': 5}}
orders2 = _make_adapter(sim2, snap2, '2026-07-07', real_holdings)
buy_manual_held = sim2.buy('272210', '한화시스템', 70400, 2, '')   # 실보유+원장부재 → 거부
buy_program_held = sim2.buy('065170', '비엘팜텍', 4000, 10, '')     # 실보유+원장존재(불타기) → 허용
buy_new = sim2.buy('005930', '삼성전자', 70000, 5, '')              # 미보유 신규 → 허용
guard_ok = (buy_manual_held is False and buy_program_held is True and buy_new is True
            and len(orders2) == 2)
results.append(('어댑터: 실잔고 이중 방어(원장 부재 종목 매수 거부)', guard_ok))
print(f"[2b] 수동보유매수={buy_manual_held} 원장보유불타기={buy_program_held} 신규={buy_new}  "
      f"{'PASS' if guard_ok else 'FAIL'}")

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

# 4) 복리: 원장 기본값 + effective_budget 계산
ledger_defaults_ok = (_default_ledger().get('realized_pnl', 'MISSING') == 0
                      and _default_ledger().get('cooldown_codes') == {})
print(f"[4a] _default_ledger()에 realized_pnl=0 + cooldown_codes 포함  {'PASS' if ledger_defaults_ok else 'FAIL'}")


def compute_effective_budget(budget, realized_pnl, real_account_value):
    """run_program_trading의 effective_budget 계산·클램프를 그대로 재현(회귀 검증용)."""
    eb = budget + realized_pnl
    if eb > real_account_value:
        eb = real_account_value
    return eb


budget = 2_000_000
realized_pnl_after_profit = 20 * (150000 - 100000)
eb1 = compute_effective_budget(budget, realized_pnl_after_profit, real_account_value=10_000_000)
compound_ok = eb1 == 3_000_000
print(f"[4b] 200만 배정 + 실현손익(+100만) -> effective_budget={eb1:,.0f}  {'PASS' if compound_ok else 'FAIL'}")

realized_pnl_after_loss = -500_000
eb2 = compute_effective_budget(budget, realized_pnl_after_loss, real_account_value=10_000_000)
loss_ok = eb2 == 1_500_000
print(f"[4c] 200만 배정 + 실현손실(-50만) -> effective_budget={eb2:,.0f}  {'PASS' if loss_ok else 'FAIL'}")

eb3 = compute_effective_budget(budget, realized_pnl=50_000_000, real_account_value=3_500_000)
clamp_ok = eb3 == 3_500_000
print(f"[4d] 실현손익 과대 -> 실제 계좌가치(350만)로 클램프: {eb3:,.0f}  {'PASS' if clamp_ok else 'FAIL'}")

results.append(('복리: 원장 기본값', ledger_defaults_ok))
results.append(('복리: 수익 반영(200만->300만)', compound_ok))
results.append(('복리: 손실 반영(200만->150만)', loss_ok))
results.append(('복리: 실제 계좌가치 클램프', clamp_ok))

# 5) [신규] 원장 GitHub API I/O — requests 모킹
class FakeRes:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeRequests:
    def __init__(self):
        self.get_queue = []
        self.put_queue = []
        self.put_bodies = []

    def get(self, url, **kw):
        return self.get_queue.pop(0) if self.get_queue else FakeRes(500)

    def put(self, url, json=None, **kw):
        self.put_bodies.append(json)
        return self.put_queue.pop(0) if self.put_queue else FakeRes(500)


_orig_requests = pt.requests
_orig_env = os.environ.get('GH_PAT')
os.environ['GH_PAT'] = 'dummy-token'
fake = FakeRequests()
pt.requests = fake
try:
    # 5a. 404 → 기본 원장 부트스트랩 (sha=None)
    fake.get_queue = [FakeRes(404)]
    led, sha = _read_ledger_fresh(log=lambda *a: None)
    boot_ok = led == _default_ledger() and sha is None
    print(f"[5a] 원장 404 -> 기본 원장 부트스트랩  {'PASS' if boot_ok else 'FAIL'}")

    # 5b. 조회 실패(HTTP 500) → (None, None) = fail-closed
    fake.get_queue = [FakeRes(500)]
    led2, sha2 = _read_ledger_fresh(log=lambda *a: None)
    fc_ok = led2 is None and sha2 is None
    print(f"[5b] 원장 조회 실패 -> fail-closed(None)  {'PASS' if fc_ok else 'FAIL'}")

    # 5c. 정상 조회 → 파싱 + sha + 기본키 보정
    raw = {'positions': {'002780': {'name': '진흥기업', 'quantity': 246, 'avg_price': 1216}},
           'last_run': '2026-07-06T11:33:00', 'sim': 'sim4_bull_daytrading', 'realized_pnl': -100}
    b64 = base64.b64encode(json.dumps(raw).encode()).decode()
    fake.get_queue = [FakeRes(200, {'content': b64, 'sha': 'abc123'})]
    led3, sha3 = _read_ledger_fresh(log=lambda *a: None)
    read_ok = (led3 is not None and sha3 == 'abc123'
               and led3['positions']['002780']['quantity'] == 246
               and led3['cooldown_codes'] == {})
    print(f"[5c] 원장 정상 조회 -> 파싱+sha+cooldown 보정  {'PASS' if read_ok else 'FAIL'}")

    # 5d. 기록: sha 충돌(409) → fresh sha 재조회 후 재시도 성공
    fake.put_queue = [FakeRes(409), FakeRes(200)]
    fake.get_queue = [FakeRes(200, {'sha': 'fresh-sha'})]
    fake.put_bodies = []
    w_ok = _write_ledger({'positions': {}, 'last_run': 'x'}, sha='stale-sha', log=lambda *a: None)
    retry_ok = w_ok is True and len(fake.put_bodies) == 2 and fake.put_bodies[1].get('sha') == 'fresh-sha'
    print(f"[5d] 원장 기록 sha 충돌 -> fresh sha 재시도  {'PASS' if retry_ok else 'FAIL'}")

    # 5e. 기록 실패(연속 500) → False (예외 없이)
    fake.put_queue = [FakeRes(500)]
    w2 = _write_ledger({'positions': {}}, sha=None, log=lambda *a: None)
    wfail_ok = w2 is False
    print(f"[5e] 원장 기록 실패 -> False(예외 없음)  {'PASS' if wfail_ok else 'FAIL'}")
finally:
    pt.requests = _orig_requests
    if _orig_env is None:
        os.environ.pop('GH_PAT', None)
    else:
        os.environ['GH_PAT'] = _orig_env

results.append(('원장 API: 404 부트스트랩', boot_ok))
results.append(('원장 API: 조회 실패 fail-closed', fc_ok))
results.append(('원장 API: 정상 파싱+sha', read_ok))
results.append(('원장 API: sha 충돌 재시도', retry_ok))
results.append(('원장 API: 기록 실패 무예외', wfail_ok))

# 6) [신규] 사이징 budget 연동
sim_b = get_simulator_by_id('sim4_bull_daytrading', initial_cash=390_000)
sizing_ok = sim_b is not None and sim_b.initial_cash == 390_000
# 가상 심 상태 파일은 오염되지 않아야 함(생성자 기본값으로 로드/유지)
sim_default = get_simulator_by_id('sim4_bull_daytrading')
default_ok = sim_default is not None and sim_default.initial_cash == 3_000_000
results.append(('사이징: initial_cash=budget 연동 + 기본값 보존', sizing_ok and default_ok))
print(f"[6] budget연동 initial_cash={getattr(sim_b, 'initial_cash', None):,} "
      f"기본={getattr(sim_default, 'initial_cash', None):,}  {'PASS' if (sizing_ok and default_ok) else 'FAIL'}")

# 7) [신규] 심 전용 유니버스 적용
class UniverseSim:
    def get_universe(self):
        return [{'code': '111111', 'price': 1000}]


class NoUniverseSim:
    def get_universe(self):
        return None


class BrokenUniverseSim:
    def get_universe(self):
        raise RuntimeError('KIS down')


pipeline_cands = [{'code': '999999', 'price': 500}]
_silent = lambda *a: None
r1 = _resolve_candidates(UniverseSim(), pipeline_cands, enrich=lambda u: u + [{'code': '222222', 'price': 2000}],
                         log=_silent, log_error=_silent)
r2 = _resolve_candidates(UniverseSim(), pipeline_cands, enrich=None, log=_silent, log_error=_silent)
r3 = _resolve_candidates(NoUniverseSim(), pipeline_cands, enrich=None, log=_silent, log_error=_silent)
r4 = _resolve_candidates(BrokenUniverseSim(), pipeline_cands, enrich=None, log=_silent, log_error=_silent)


def _enrich_fail(u):
    raise RuntimeError('enrich down')


r5 = _resolve_candidates(UniverseSim(), pipeline_cands, enrich=_enrich_fail, log=_silent, log_error=_silent)
uni_ok = (len(r1) == 2 and r1[1]['code'] == '222222'   # enrich 경로
          and r2[0]['code'] == '111111'                  # 미보강 유니버스
          and r3 is pipeline_cands                       # universe 없음 → fallback
          and r4 is pipeline_cands                       # universe 예외 → fallback
          and r5[0]['code'] == '111111')                 # enrich 실패 → 원본 유니버스
results.append(('유니버스: enrich/미보강/fallback/예외 경로', uni_ok))
print(f"[7] enrich={len(r1)} 미보강={r2[0]['code']} fallback={r3 is pipeline_cands} "
      f"예외fallback={r4 is pipeline_cands} enrich실패={r5[0]['code']}  {'PASS' if uni_ok else 'FAIL'}")

# 8) [신규] 전략 플래그 머지
positions_m = {'AAA': {'name': 'A', 'quantity': 50, 'avg_price': 1000},
               'BBB': {'name': 'B', 'quantity': 30, 'avg_price': 2000}}
snap_pf = {'AAA': {'name': 'A', 'quantity': 50, 'avg_price': 999,  # 수량/평단은 머지 금지
                   'partial_sold': True, 'partial_sold_date': '2026-07-07', 'peak_price': 1100},
           'BBB': {'name': 'B', 'quantity': 30, 'avg_price': 2000, 'partial_sold': True}}
_merge_strategy_flags(positions_m, snap_pf, failed_codes={'BBB'})
merge_ok = (positions_m['AAA'].get('partial_sold') is True
            and positions_m['AAA'].get('partial_sold_date') == '2026-07-07'
            and positions_m['AAA'].get('peak_price') == 1100
            and positions_m['AAA']['avg_price'] == 1000        # 평단 보존
            and 'partial_sold' not in positions_m['BBB'])       # 실패 종목 머지 제외
results.append(('플래그 머지: partial_sold 보존 + 실패 종목 제외 + 평단 보호', merge_ok))
print(f"[8] AAA plag={positions_m['AAA'].get('partial_sold')} avg={positions_m['AAA']['avg_price']} "
      f"BBB제외={'partial_sold' not in positions_m['BBB']}  {'PASS' if merge_ok else 'FAIL'}")

# 9) [신규] Sim4-1 통합: 진흥기업 실사고 시나리오 (-22.4% 보유 → 손절 + 쿨다운)
sim41 = get_simulator_by_id('sim4_bull_daytrading', initial_cash=390_000)
from datetime import date, timedelta as _td
yesterday = (date.today() - _td(days=1)).isoformat()
snap9 = {
    'cash': 390_000 - (1230 * 1216), 'invested': 1230 * 1216,
    'portfolio': {'002780': {'name': '진흥기업', 'quantity': 1230, 'avg_price': 1216,
                             'peak_price': 1216, 'entry_date': yesterday, 'is_scaled_out': False}},
    'total_fees': 0, 'history': [390_000], 'daily_trades': [], 'peak_nav': 390_000,
    'market_index_healthy': True, 'cooldown_codes': {},
}
snap9['cash'] = max(0.0, snap9['cash'])
orders9 = _make_adapter(sim41, snap9, date.today().isoformat(),
                        real_holdings={'002780': {'qty': 1230}})
sim41.run([], current_prices={'002780': 944})   # -22.4%
sell9 = [o for o in orders9 if o['side'] == 'sell' and o['code'] == '002780']
integ_ok = (len(sell9) == 1 and sell9[0]['qty'] == 1230
            and '002780' in snap9['cooldown_codes']
            and '002780' not in snap9['portfolio'])
results.append(('Sim4-1 통합: -22% 손절 전량매도 + 쿨다운 기록', integ_ok))
print(f"[9] 매도주문={len(sell9)}건 qty={sell9[0]['qty'] if sell9 else 0} "
      f"쿨다운={'002780' in snap9['cooldown_codes']} reason={sell9[0]['reason'] if sell9 else '-'}  "
      f"{'PASS' if integ_ok else 'FAIL'}")

allok = all(ok for _, ok in results)
print("\n결과:", "ALL PASS" if allok else "CHECK ABOVE")
for name, ok in results:
    print(f"  {'O' if ok else 'X'} {name}")
sys.exit(0 if allok else 1)
