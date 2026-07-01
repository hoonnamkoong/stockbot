"""리베로 실시간 나우캐스트 예측기 검증 (P0/P1 병렬 채점).

네트워크/장중 데이터 없이 핵심 로직을 합성 데이터로 검증한다:
1. _zone / _project(P1) 순수 함수
2. score_pending: 시각별 적중률·MAE·preferred 선택
   - 드리프트 시나리오 → P1(궤적 보정) 승
   - 노이즈(마팅게일) 시나리오 → P0(원시 최신) 승
3. run() 스모크: 합성 candidate 1회 실행 시 live/confirmed/metrics/intraday 로깅

실행: python scratch/verify_libero_nowcast.py
주의: run()/score_pending이 로컬 sim_libero_state.json을 갱신 → 실행 후 git 복원 권장.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.strategy.simulators.sim0_libero import LiberoSimulator

Z = LiberoSimulator._zone
PROJ = LiberoSimulator._project


def make_candidates(breadth_pct, n=100):
    """breadth_pct%가 상승(change_rate>0)인 합성 candidate n개."""
    ups = round(breadth_pct / 100 * n)
    out = []
    for i in range(n):
        rate = 1.0 if i < ups else -1.0
        base = 1000
        out.append({'code': f'{i:06d}', 'change_rate': rate,
                    'sparkline_price': [base, base + (10 if rate > 0 else -10)]})
    return out


def build_day(p0_seq):
    """P0 breadth 시퀀스로 하루 장중 예측 로그 생성 (P1은 run()과 동일하게 _project로)."""
    samples = []
    for i, b0 in enumerate(p0_seq):
        priors = [s['breadth_p0'] for s in samples]
        b1 = PROJ(priors + [b0])
        samples.append({'ts': f'{9 + i:02d}:00',
                        'breadth_p0': b0, 'regime_p0': Z(b0),
                        'breadth_p1': b1, 'regime_p1': Z(b1),
                        'momentum': 0, 'trend': 0})
    return samples


def fresh_sim():
    s = LiberoSimulator()
    for k in ('prediction_scores', 'score_totals', 'intraday', 'calibration_log'):
        s.state.pop(k, None)
    s.state['preferred_predictor'] = 'P0'
    return s


results = []

# ---- 1) 순수 함수 ----
assert Z(70) == 'BULL' and Z(50) == 'SIDEWAYS' and Z(30) == 'BEAR'
assert PROJ([]) == 0.0 and PROJ([50]) == 50.0
p = PROJ([30, 40, 50])            # 상승 추세 → EWMA+slope 로 50 이상 투영
assert p >= 50, p
results.append(('순수 함수 _zone/_project', True))
print(f"[1] _project([30,40,50])={p}  PASS")

# ---- 2a) 드리프트 시나리오: P1 승 기대 ----
# EOD actual=62(BULL). P0가 아침엔 BULL 미달이다가 상승해 마감 62.
# P1은 상승 궤적을 외삽해 BULL을 더 일찍 적중 → 적중률 우위 기대.
sim = fresh_sim()
sim.state['intraday'] = {'2026-06-01': build_day([46, 52, 57, 60, 62])}
sim.score_pending('2026-06-01', 62.0)
sc = sim.state['prediction_scores']['2026-06-01']
drift_ok = sc['p1']['hit_rate'] >= sc['p0']['hit_rate'] and sim.state['preferred_predictor'] == 'P1'
results.append(('드리프트 → P1 승', drift_ok))
print(f"[2a] 드리프트: P0 적중률={sc['p0']['hit_rate']} P1 적중률={sc['p1']['hit_rate']} "
      f"→ preferred={sim.state['preferred_predictor']}  {'PASS' if drift_ok else 'FAIL'}")

# ---- 2b) 노이즈(마팅게일) 시나리오: P0 승 기대 ----
# EOD actual=50(SIDEWAYS). P0가 50 근처서 진동(모두 SIDEWAYS, 전부 적중).
# P1은 진동에 속도 외삽이 과반응해 경계(BULL/BEAR)로 튀어 오분류 → P0 우위 기대.
sim2 = fresh_sim()
sim2.state['intraday'] = {'2026-06-02': build_day([44, 57, 43, 58, 50])}
sim2.score_pending('2026-06-02', 50.0)
sc2 = sim2.state['prediction_scores']['2026-06-02']
noise_ok = sc2['p0']['hit_rate'] >= sc2['p1']['hit_rate'] and sim2.state['preferred_predictor'] == 'P0'
results.append(('노이즈 → P0 승', noise_ok))
print(f"[2b] 노이즈: P0 적중률={sc2['p0']['hit_rate']} P1 적중률={sc2['p1']['hit_rate']} "
      f"→ preferred={sim2.state['preferred_predictor']}  {'PASS' if noise_ok else 'FAIL'}")

# ---- 2c) idempotency & calibration_log ----
before = dict(sim.state['prediction_scores']['2026-06-01'])
sim.score_pending('2026-06-01', 62.0)   # 재호출 → 무변화
idem_ok = sim.state['prediction_scores']['2026-06-01'] == before
cal_ok = sim.state['calibration_log'][-1]['date'] == '2026-06-01' and \
    'gap' in sim.state['calibration_log'][-1]
results.append(('idempotent + calibration_log', idem_ok and cal_ok))
print(f"[2c] 재채점 무변화={idem_ok}, calibration_log gap 기록={cal_ok}  "
      f"{'PASS' if (idem_ok and cal_ok) else 'FAIL'}")

# ---- 3) run() 스모크 ----
sim3 = fresh_sim()
st = sim3.run(make_candidates(55))   # breadth≈55 → SIDEWAYS
run_ok = ('live_regime' in st and 'confirmed_regime' in st and 'intraday' in st
          and 'breadth_p0' in st['metrics'] and 'breadth_p1' in st['metrics']
          and len(next(iter(st['intraday'].values()))) >= 1)
results.append(('run() 이중트랙·intraday 로깅', run_ok))
print(f"[3] run(): live={st.get('live_regime')} confirmed={st.get('confirmed_regime')} "
      f"breadth_p0={st['metrics']['breadth_p0']} intraday샘플={len(next(iter(st['intraday'].values())))}  "
      f"{'PASS' if run_ok else 'FAIL'}")

allok = all(ok for _, ok in results)
print("\n결과:", "ALL PASS" if allok else "CHECK ABOVE")
for name, ok in results:
    print(f"  {'O' if ok else 'X'} {name}")
sys.exit(0 if allok else 1)
