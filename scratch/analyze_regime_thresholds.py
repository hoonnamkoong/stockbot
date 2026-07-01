"""리베로 국면 임계값 재보정 근거 분석.

EOD CSV(kospi_top100_close.csv) 100거래일로 Sim0 방식의 일별 (breadth, momentum, trend)를
재구성하고, 현행 classify_regime(breadth>=60 AND momentum>=2 AND trend>=20 → BULL 등)의
국면 발생률과 '게이트 차단'(breadth는 조건 충족하나 momentum/trend에 막혀 SIDEWAYS로 간 날)을
집계한다. 임계값 조정은 이 분포에 근거해야 한다(임의 조정=오버피팅).

실행: python scratch/analyze_regime_thresholds.py
주의: 여기 momentum/trend는 20일 CSV 종가 기반(라이브 나우캐스트도 동일 소스라 근사 대표).
"""
import os
import sys
import statistics

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.strategy.simulators.sim0_libero import LiberoSimulator

CSV = 'output/kospi_top100_close.csv'
WINDOW = 20

sim = LiberoSimulator()

with open(CSV, 'r', encoding='utf-8-sig') as f:
    lines = [l for l in f.read().split('\n') if l.strip()]
header = lines[0].split(',')
rows = [ln.split(',') for ln in lines[1:]]
ncol = len(header)


def val(r, j):
    if j < len(r) and r[j].strip():
        try:
            v = float(r[j].strip())
            return v if v > 0 else None
        except ValueError:
            return None
    return None


records = []
for i in range(WINDOW, len(rows)):
    breadth_up = total = 0
    period_changes, adxs = [], []
    for j in range(1, ncol):
        spark = [val(rows[k], j) for k in range(i - WINDOW + 1, i + 1)]
        spark = [x for x in spark if x is not None]
        prev, curr = val(rows[i - 1], j), val(rows[i], j)
        if prev is not None and curr is not None:
            total += 1
            if curr > prev:
                breadth_up += 1
        if len(spark) >= 2:
            period_changes.append(sim.calc_period_change(spark))
            adxs.append(sim.calculate_adx(spark))
    if total == 0:
        continue
    breadth = round(breadth_up / total * 100, 1)
    momentum = round(statistics.median(period_changes), 2) if period_changes else 0.0
    trend = round(statistics.median(adxs), 1) if adxs else 0.0
    regime = sim.classify_regime(breadth, momentum, trend)
    records.append({'date': rows[i][0], 'breadth': breadth, 'momentum': momentum,
                    'trend': trend, 'regime': regime})

n = len(records)
print(f"분석 대상: {n}거래일 (WINDOW={WINDOW})\n")


def dist(vals, label):
    vs = sorted(vals)
    q = lambda p: vs[min(len(vs) - 1, int(p * len(vs)))]
    print(f"[{label}] min={vs[0]:.1f} p25={q(.25):.1f} median={statistics.median(vs):.1f} "
          f"p75={q(.75):.1f} max={vs[-1]:.1f} mean={statistics.mean(vs):.1f}")


dist([r['breadth'] for r in records], 'breadth')
dist([r['momentum'] for r in records], 'momentum(20일 기간변동 중앙값)')
dist([r['trend'] for r in records], 'trend(ADX 근사)')

# 국면 발생률
from collections import Counter
rc = Counter(r['regime'] for r in records)
print("\n[현행 규칙 국면 발생률]")
for k in ('BULL', 'SIDEWAYS', 'BEAR'):
    print(f"  {k:9s}: {rc.get(k,0):3d}일 ({rc.get(k,0)/n*100:4.1f}%)")

# 게이트 차단 분석: breadth만으로는 BULL/BEAR인데 momentum/trend에 막힌 날
b_bull = [r for r in records if r['breadth'] >= 60]
b_bear = [r for r in records if r['breadth'] <= 40]
bull_blocked = [r for r in b_bull if r['regime'] != 'BULL']
bear_blocked = [r for r in b_bear if r['regime'] != 'BEAR']
print("\n[게이트 차단 (breadth 조건은 충족하나 momentum/trend에 막힘)]")
print(f"  breadth>=60 인 날: {len(b_bull):3d}  그 중 BULL 미달: {len(bull_blocked):3d} "
      f"({len(bull_blocked)/max(len(b_bull),1)*100:4.1f}%)")
print(f"  breadth<=40 인 날: {len(b_bear):3d}  그 중 BEAR 미달: {len(bear_blocked):3d} "
      f"({len(bear_blocked)/max(len(b_bear),1)*100:4.1f}%)")

# 차단 사유 분해 (momentum vs trend 어느 게이트가 막았나)
def block_reason(r, kind):
    if kind == 'BULL':
        m = r['momentum'] < 2.0
        t = r['trend'] < 20
    else:
        m = r['momentum'] > -2.0
        t = r['trend'] < 15
    return m, t

for kind, blocked in (('BULL', bull_blocked), ('BEAR', bear_blocked)):
    if not blocked:
        continue
    mcnt = sum(1 for r in blocked if block_reason(r, kind)[0])
    tcnt = sum(1 for r in blocked if block_reason(r, kind)[1])
    print(f"    {kind} 차단 {len(blocked)}건 사유: momentum 게이트 {mcnt}건, trend 게이트 {tcnt}건")

# breadth-only 국면 대비 (게이트 없이 breadth 60/40만)
bo = Counter('BULL' if r['breadth'] >= 60 else 'BEAR' if r['breadth'] <= 40 else 'SIDEWAYS'
             for r in records)
print("\n[참고: breadth 단독(게이트 없음) 국면 발생률]")
for k in ('BULL', 'SIDEWAYS', 'BEAR'):
    print(f"  {k:9s}: {bo.get(k,0):3d}일 ({bo.get(k,0)/n*100:4.1f}%)")
