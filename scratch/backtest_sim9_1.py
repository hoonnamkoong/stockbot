"""심9-1(돈치안) 백테스트 — KOSPI top100 실제 일봉 종가.

데이터: output/kospi_top100_close.csv (100거래일 2026-02-24~07-21 × 100종목).
버즈 유니버스(월별 엑셀)는 종목당 평균 4.9일만 관측돼 20일 채널을 만들 수 없다.
이 CSV는 종목당 100일 연속이라 채널·ATR·청산이 전부 제대로 계산된다.

심 코드의 상수·ATR 식을 그대로 import해서 쓴다(수식이 갈라지지 않도록).

한계:
  - 유니버스가 KOSPI top100이다. 실제 심9-1은 버즈 후보에서 돈다 — 대형주는
    변동성이 작아 돌파 빈도·폭이 다르다. 방향성 확인용이지 수익률 이식은 아니다.
  - CSV에 거래량/거래대금이 없어 '거래대금 횡단면 z > 0' 조건을 적용하지 못했다.
    없는 값을 지어내지 않고 조건을 뺀 채로 측정한다(신호가 더 많이 나는 쪽).
  - 채널은 항상 '당일 제외 직전 20일'로 계산한다(라이브에서 수급 테이블이
    장중에 당일 행을 싣지 않는 것과 같은 상태).
"""
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.strategy.simulators.sim9_1_donchian import (
    CHANNEL_DAYS, EXIT_DAYS, ATR_STOP_MULT, MAX_HOLDINGS, POSITION_WEIGHT, _atr)

CSV_PATH = os.path.join(os.path.dirname(__file__), '..', 'output', 'kospi_top100_close.csv')
INITIAL_CASH = 3_000_000
BUY_FEE = 0.00015
SELL_FEE = 0.00015 + 0.0018

rows = list(csv.DictReader(open(CSV_PATH, encoding='utf-8-sig')))
dates = [r['date'] for r in rows]
cols = [c for c in rows[0] if c != 'date']
codes = [c.split('_', 1)[0] for c in cols]
names = {c.split('_', 1)[0]: (c.split('_', 1)[1] if '_' in c else c) for c in cols}

series = {code: [] for code in codes}
for r in rows:
    for col, code in zip(cols, codes):
        v = r.get(col, '').strip()
        series[code].append(float(v) if v else None)

print(f"데이터: {len(dates)}거래일 × {len(codes)}종목 ({dates[0]} ~ {dates[-1]})")


def hist_at(code, t, n):
    """t일 '직전' n일 종가 (당일 제외). 결측이 섞이면 None."""
    if t < n:
        return None
    h = series[code][t - n:t]
    return None if any(x is None or x <= 0 for x in h) else h


cash = INITIAL_CASH
holdings = {}          # code -> (qty, entry_px, entry_t)
trades = []
nav_curve = []

for t in range(CHANNEL_DAYS, len(dates)):
    # 1. 청산
    for code, (qty, epx, et) in list(holdings.items()):
        px = series[code][t]
        if px is None or px <= 0:
            continue
        h20 = hist_at(code, t, CHANNEL_DAYS)
        reason = None
        if h20 and px <= epx - ATR_STOP_MULT * _atr(h20):
            reason = 'ATR손절'
        else:
            h10 = hist_at(code, t, EXIT_DAYS)
            if h10 and px < min(h10):
                reason = '채널이탈'
        if reason:
            proceeds = qty * px * (1 - SELL_FEE)
            cost = qty * epx * (1 + BUY_FEE)
            cash += proceeds
            trades.append((dates[t], code, (proceeds / cost - 1) * 100, reason,
                           t - et))
            del holdings[code]

    # 2. 진입 — 20일 채널 상단 돌파
    nav = cash + sum(q * (series[c][t] or e) for c, (q, e, _) in holdings.items())
    target = nav * POSITION_WEIGHT
    for code in codes:
        if len(holdings) >= MAX_HOLDINGS:
            break
        if code in holdings:
            continue
        px = series[code][t]
        h20 = hist_at(code, t, CHANNEL_DAYS)
        if px is None or px <= 0 or not h20 or px <= max(h20):
            continue
        qty = int(target / px)
        cost = qty * px * (1 + BUY_FEE)
        if qty <= 0 or cost > cash:
            continue
        cash -= cost
        holdings[code] = (qty, px, t)

    nav_curve.append(cash + sum(q * (series[c][t] or e) for c, (q, e, _) in holdings.items()))

final_nav = nav_curve[-1]
wins = [x for _, _, x, _, _ in trades if x > 0]
rets = [x for _, _, x, _, _ in trades]
holds = [d for _, _, _, _, d in trades]

print(f"\n[심9-1 돈치안]")
print(f"  총 거래 {len(trades)}건 (기간 {len(dates)-CHANNEL_DAYS}거래일 ≈ {(len(dates)-CHANNEL_DAYS)/21:.1f}개월)")
if rets:
    print(f"  거래당 평균 순수익 {sum(rets)/len(rets):+.2f}%, 승률 {len(wins)/len(rets)*100:.1f}%")
    print(f"  최대 {max(rets):+.1f}% / 최소 {min(rets):+.1f}% / 평균 보유 {sum(holds)/len(holds):.1f}일")
    from collections import Counter
    print(f"  청산 사유:", dict(Counter(r for _, _, _, r, _ in trades)))
print(f"  NAV {INITIAL_CASH:,} → {final_nav:,.0f}원 ({(final_nav/INITIAL_CASH-1)*100:+.2f}%)")

# 기저: 같은 기간 유니버스 동일가중 매수 후 보유
base = []
for code in codes:
    s, e = series[code][CHANNEL_DAYS], series[code][-1]
    if s and e and s > 0:
        base.append(e / s - 1)
print(f"  기저(top100 동일가중 매수후보유): {sum(base)/len(base)*100:+.2f}%")

# 배포 게이트 (심9와 동일 기준으로 판정)
if rets:
    m, w, f = sum(rets)/len(rets), len(wins)/len(rets)*100, len(trades)/((len(dates)-CHANNEL_DAYS)/21)
    print(f"\n[배포 게이트] 평균 {m:+.2f}% {'PASS' if m >= 2.0 else 'FAIL'} / "
          f"승률 {w:.1f}% {'PASS' if w >= 55 else 'FAIL'} / "
          f"월 {f:.1f}건 {'PASS' if f <= 25 else 'FAIL'}")

# 소수 극단값 의존도 점검 — 추세추종은 원래 승률이 낮고 소수 대박이 끈다.
srt = sorted(trades, key=lambda x: -x[2])
print("\n[상위 5건]")
for d, c, r, why, hd in srt[:5]:
    print(f"  {d} {names.get(c,c)}({c}) {r:+.1f}% ({why}, {hd}일 보유)")
for k in (1, 2, 3):
    rest = [x[2] for x in srt[k:]]
    print(f"  상위 {k}건 제외 평균: {sum(rest)/len(rest):+.2f}%")
