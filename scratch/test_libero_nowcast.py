"""
리베로 나우캐스트(시간당 실측 기록·예측·채점) 단위 테스트 — 네트워크 없음.
실행: PYTHONPATH=. python scratch/test_libero_nowcast.py
"""
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '.')
from src.strategy.simulators.sim0_libero import LiberoSimulator

KST = timezone(timedelta(hours=9))


def fresh_sim():
    sim = LiberoSimulator()
    sim.state = {'metrics': {}, 'calibration_log': []}
    sim.save_state = lambda *a, **k: None
    return sim


def kst(h, m=0, day=8):
    return datetime(2026, 7, day, h, m, tzinfo=KST)


results = []


def check(name, cond):
    results.append((name, cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


# ── T1: 실측 기록 + 예측 생성 + 다음 시간 채점 ──────────────────
sim = fresh_sim()
sim.update_nowcast(40.0, now_kst=kst(10))          # 10시: 실측 40, 예측 생성
intr = sim.state['intraday']
check('T1a 실측 1건 기록', len(intr['measurements']) == 1 and intr['measurements'][0]['t'] == '10:00')
h1 = [p for p in intr['predictions'] if p['type'] == 'h1']
eod = [p for p in intr['predictions'] if p['type'] == 'eod']
check('T1b +1h/EOD 예측 각 1건', len(h1) == 1 and len(eod) == 1 and h1[0]['target'] == '11:00')
check('T1c 측정 1건이면 속도 0 → 예측=실측', h1[0]['value'] == 40.0)

sim.update_nowcast(46.0, now_kst=kst(11))          # 11시: 실측 46 → 10시의 +1h 예측 채점
log = sim.state['intraday_score_log']
check('T2a 11시에 10시 +1h 예측 채점', len(log) == 1 and log[0]['type'] == 'h1')
check('T2b 갭 = 예측(40) - 실측(46) = -6', log[0]['gap'] == -6.0)
h1_11 = [p for p in sim.state['intraday']['predictions'] if p['type'] == 'h1' and p['made_at'] == '11:00']
check('T2c 속도 외삽: 11시 +1h 예측 = 46 + (46-40) = 52', h1_11 and h1_11[0]['value'] == 52.0)

# ── T3: 같은 시각 중복 호출 → 측정·예측 중복 없음 ──────────────
n_m = len(sim.state['intraday']['measurements'])
n_p = len(sim.state['intraday']['predictions'])
sim.update_nowcast(47.0, now_kst=kst(11, 20))
check('T3 같은 시간대 재실행 시 중복 기록 없음',
      len(sim.state['intraday']['measurements']) == n_m
      and len(sim.state['intraday']['predictions']) == n_p)

# ── T4: 클램프 0~100 ───────────────────────────────────────────
sim2 = fresh_sim()
sim2.update_nowcast(90.0, now_kst=kst(10))
sim2.update_nowcast(99.0, now_kst=kst(11))
h1v = [p for p in sim2.state['intraday']['predictions'] if p['type'] == 'h1' and p['made_at'] == '11:00'][0]['value']
check('T4 예측 클램프 상한 100', h1v == 100.0)

# ── T5: 15시 런 → +1h 예측 미생성(장 마감 지남), EOD 예측은 생성 ─
sim3 = fresh_sim()
sim3.update_nowcast(50.0, now_kst=kst(15))
preds = sim3.state['intraday']['predictions']
check('T5 15시엔 h1 없음 · eod 있음',
      not [p for p in preds if p['type'] == 'h1'] and [p for p in preds if p['type'] == 'eod'])

# ── T6: 결측 시각 백필로 채점 ──────────────────────────────────
sim4 = fresh_sim()
sim4.update_nowcast(40.0, now_kst=kst(10))
called = {}
def fake_backfill(hhmm):
    called['t'] = hhmm
    return 44.0
# 11시 런이 없었고 12시 런에서 11시 예측을 백필로 채점
sim4.update_nowcast(48.0, now_kst=kst(12), backfill=fake_backfill)
log4 = sim4.state['intraday_score_log']
check('T6a 백필 호출됨 (11:00)', called.get('t') == '11:00')
check('T6b 백필 실측(44)으로 채점: gap=40-44=-4', any(e['gap'] == -4.0 and e['type'] == 'h1' for e in log4))

# ── T7: EOD 확정 채점 + calibration 기록 + 멱등성 ──────────────
sim5 = fresh_sim()
sim5.update_nowcast(40.0, now_kst=kst(10))
sim5.update_nowcast(50.0, now_kst=kst(11))
sim5.finalize_eod(38.0, now_kst=kst(16))
eod_scores = [e for e in sim5.state['intraday_score_log'] if e['type'] == 'eod']
check('T7a EOD 예측 2건 모두 채점', len(eod_scores) == 2)
cal = sim5.state['calibration_log']
first_eod_pred = [p for p in sim5.state['intraday']['predictions'] if p['type'] == 'eod'][0]['value']
check('T7b calibration 1건 = 첫 EOD 예측 vs 확정 실측',
      len(cal) == 1 and cal[0]['libero_breadth'] == round(first_eod_pred, 1)
      and cal[0]['actual_kospi_breadth'] == 38.0 and cal[0].get('v') == 2)
n_log = len(sim5.state['intraday_score_log'])
sim5.finalize_eod(38.0, now_kst=kst(19))
check('T7c finalize 재호출 멱등 (채점·calibration 중복 없음)',
      len(sim5.state['intraday_score_log']) == n_log and len(sim5.state['calibration_log']) == 1)

# ── T8: 날짜 바뀌면 intraday 리셋, 점수 로그는 유지 ────────────
sim5.update_nowcast(60.0, now_kst=kst(10, day=9))
check('T8 날짜 롤오버 시 intraday 리셋 + score_log 유지',
      sim5.state['intraday']['date'] == '2026-07-09'
      and len(sim5.state['intraday']['measurements']) == 1
      and len(sim5.state['intraday_score_log']) == n_log)

# ── T9: run()에 라이브 breadth 주입 시 metrics 반영 ────────────
sim6 = fresh_sim()
sim6.state.update({'cash': 0, 'portfolio': {}})
cands = [{'code': '000001', 'name': 'X', 'change_rate': '-2.0', 'sparkline_price': [100, 99], 'foreign_change': 0}]
sim6.live_breadth_info = (72.5, 100)
sim6.run(cands)
check('T9a 라이브 주입 시 breadth=72.5·source=top100_live',
      sim6.state['metrics']['breadth_score'] == 72.5
      and sim6.state.get('breadth_source') == 'top100_live'
      and sim6.state['sample_size'] == 100)
sim7 = fresh_sim()
sim7.state.update({'cash': 0, 'portfolio': {}})
sim7.live_breadth_info = None
sim7.run(cands)
check('T9b 라이브 실패 시 기존 후보 기반 폴백', sim7.state.get('breadth_source') == 'candidates')

fails = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(fails)}/{len(results)} PASS" + (f" — FAIL: {fails}" if fails else " — ALL PASS"))
sys.exit(1 if fails else 0)
