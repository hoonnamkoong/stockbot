"""심8(선행매집) 신호 검증 — 리포트 엑셀의 52주·수급추정 컬럼 사용.

월별 엑셀(trending_integrated)에는 52주·수급추정 컬럼이 없지만
리포트 엑셀(monthly_research)에는 있다. 신호는 여기서 만들고,
수익률은 월별 엑셀 패널의 복원 종가로 측정한다.

  git show db-data:data/reports/monthly_research_2026-07.xlsx > scratch/mr_2026-07.xlsx
  git show db-data:data/trending_integrated_2026-07.xlsx      > scratch/ti_2026-07.xlsx

한계:
  - 군중축을 `unique_posters` 대신 `Posts Count`로 대체했다(고유작성자는 오늘 배선분).
    도배 배제가 빠진 프록시라 군중축이 실제보다 거칠다.
  - 리포트 엑셀은 '텔레그램 보고 종목'만 담아 하루 횡단면이 얇다.
    표본 10 미만인 날은 심 코드와 동일하게 신호를 만들지 않는다(fail-closed).
  - 청산(정보축 반전/앵커 이탈/트레일링)은 검증하지 않는다. 진입 신호에
    +1/+3/+5일 초과수익이 있는지만 본다.
"""
import numpy as np
import pandas as pd
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.strategy.simulators.sim8_accumulation import (
    NEAR_FLOOR, NEAR_ACCUM_MAX, NEAR_BREAK, INFO_ACCUM_MIN, CONSENSUS_BOOST,
    MIN_SAMPLE, MIN_AMOUNT, _zmap)

SP = os.path.dirname(__file__)

# ── 가격 패널 (월별 엑셀) ────────────────────────────────
ti = pd.concat([pd.read_excel(f"{SP}/ti_2026-{m}.xlsx") for m in ("06", "07")],
               ignore_index=True)
ti["ts"] = pd.to_datetime(ti["데이터_수집시각"], errors="coerce")
ti = ti.dropna(subset=["ts"])
ti["d"] = ti["ts"].dt.normalize()
for c in ("현재가", "전일종가"):
    ti[c] = pd.to_numeric(ti[c], errors="coerce")
ti = ti[(ti["현재가"] > 0) & ti["code"].notna()].copy()
ti["code"] = ti["code"].astype(str).str.zfill(6)
ti = ti.sort_values("ts")

days = sorted(ti["d"].unique())
pos = {d: i for i, d in enumerate(days)}
g = ti.groupby(["code", "d"])
p = pd.DataFrame({"last_px": g["현재가"].last(), "prev_close": g["전일종가"].last()}).reset_index()
p = p.sort_values(["code", "d"])
p["next_prev_close"] = p.groupby("code")["prev_close"].shift(-1)
p["next_d"] = p.groupby("code")["d"].shift(-1)
p["gap_days"] = p.apply(lambda r: (pos.get(r["next_d"], np.nan) - pos[r["d"]])
                        if pd.notna(r["next_d"]) else np.nan, axis=1)
p["close"] = np.where((p["gap_days"] == 1) & (p["next_prev_close"] > 0),
                      p["next_prev_close"], p["last_px"])
close_map = {(r.code, r.d): r.close for r in p.itertuples() if r.close > 0}


def fwd(code, d, k):
    """d일 종가 → k거래일 뒤 종가 수익률 %. 둘 중 하나라도 없으면 None."""
    i = pos.get(d)
    if i is None or i + k >= len(days):
        return None
    a, b = close_map.get((code, d)), close_map.get((code, days[i + k]))
    return None if not a or not b else (b / a - 1) * 100


# ── 신호 재료 (리포트 엑셀) ──────────────────────────────
mr = pd.concat([pd.read_excel(f"{SP}/mr_2026-{m}.xlsx") for m in ("06", "07")],
               ignore_index=True)
mr["ts"] = pd.to_datetime(mr["DateTime"], errors="coerce")
mr = mr.dropna(subset=["ts"])
mr["d"] = mr["ts"].dt.normalize()
mr["code"] = mr["Code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
num = ["Current Price", "Amount", "Frgn Est NetBuy", "Inst Est NetBuy",
       "Foreign Change", "Posts Count", "W52 High", "W52 Low"]
for c in num:
    mr[c] = pd.to_numeric(mr.get(c), errors="coerce")
mr = mr.sort_values("ts").groupby(["code", "d"], as_index=False).last()  # 하루 마지막 관측

print(f"리포트 엑셀: {len(mr)}종목-일, {mr['code'].nunique()}종목, {mr['d'].nunique()}일")
print(f"가격 패널과 매칭: {sum((r.code, r.d) in close_map for r in mr.itertuples())}건")

# ── 심8 신호 재현 ────────────────────────────────────────
sig_a, sig_b, universe, thin_days = [], [], [], 0
for d, sub in mr.groupby("d"):
    sub = sub[(sub["Current Price"] > 0)]
    if len(sub) < MIN_SAMPLE:
        thin_days += 1
        continue
    recs = sub.fillna(0).to_dict('records')
    rows = []
    for r in recs:
        denom = max(float(r['Amount']), 1.0)
        rows.append((r['code'],
                     r['Frgn Est NetBuy'] * r['Current Price'] / denom,
                     r['Inst Est NetBuy'] * r['Current Price'] / denom,
                     r['Foreign Change'],
                     r['Posts Count']))
    zf = _zmap([(x[0], x[1]) for x in rows])
    zo = _zmap([(x[0], x[2]) for x in rows])
    zc = _zmap([(x[0], x[3]) for x in rows])
    crowd = _zmap([(x[0], x[4]) for x in rows])
    zamt = _zmap([(r['code'], float(r['Amount'])) for r in recs])
    if not zf or not zo or not zc:
        thin_days += 1
        continue

    info = {}
    for code, fr, orr, _, _ in rows:
        if code in zf and code in zo and code in zc:
            v = zf[code] + zo[code] + zc[code]
            if fr > 0 and orr > 0:
                v *= CONSENSUS_BOOST
            info[code] = v

    for r in recs:
        code, price = r['code'], r['Current Price']
        hi, lo, amount = r['W52 High'], r['W52 Low'], r['Amount']
        if hi <= 0 or lo <= 0 or amount < MIN_AMOUNT:
            continue
        near = price / hi
        iv, cv, av = info.get(code), crowd.get(code), zamt.get(code)
        if iv is None or near < NEAR_FLOOR:
            continue
        universe.append((code, r['d']))
        if NEAR_FLOOR <= near < NEAR_ACCUM_MAX and iv > INFO_ACCUM_MIN and cv is not None and cv < 0:
            sig_a.append((code, r['d']))
        if near >= NEAR_BREAK and iv > 0 and av is not None and av > 0:
            sig_b.append((code, r['d']))

print(f"표본 부족으로 스킵한 날: {thin_days}일")


def summarize(label, pairs, base_pairs):
    print(f"\n■ {label} — 신호 {len(pairs)}건")
    if not pairs:
        return
    for k in (1, 3, 5):
        v = [x for x in (fwd(c, d, k) for c, d in pairs) if x is not None]
        b = [x for x in (fwd(c, d, k) for c, d in base_pairs) if x is not None]
        if len(v) < 5:
            print(f"   +{k}일: 측정 {len(v)}건 — 표본 부족")
            continue
        print(f"   +{k}일: 표본 {len(v):>3}  평균 {np.mean(v):+6.2f}%  "
              f"승률 {np.mean([x > 0 for x in v])*100:4.1f}%  "
              f"기저 {np.mean(b):+.2f}%  초과 {np.mean(v)-np.mean(b):+.2f}%p")


summarize("심8-A 매집 (52주 85~98% + 정보축>1.5 + 군중 미도착)", sig_a, universe)
summarize("심8-B 돌파 (52주 신고가 + 정보축>0 + 거래대금z>0)", sig_b, universe)
summarize("[대조] 앵커 구간 전체 (52주 85% 이상)", universe, universe)
