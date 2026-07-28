"""심9 익절/손절 브래킷의 순효과 — 동일 표본·동일 진입가에서 분리.

V0(실측 재현) 표본을 고정하고 청산 규칙만 바꾼다:
  없음 / 익절만 / 손절만 / 둘 다.
설계 스펙은 ±3% 브래킷을 얹었지만 실측에는 브래킷이 없었다. 얹은 적 없는 규칙을
검증 없이 코드에 넣으면 실측 근거가 그대로 무효가 된다.
"""
import numpy as np
import pandas as pd
import os

SP = os.path.dirname(__file__)
BUY_FEE, SELL_FEE = 0.00015, 0.00015 + 0.0018

df = pd.concat([pd.read_excel(f"{SP}/ti_2026-{m}.xlsx") for m in ("06", "07")],
               ignore_index=True)
df["ts"] = pd.to_datetime(df["데이터_수집시각"], errors="coerce")
df = df.dropna(subset=["ts"])
df["d"] = df["ts"].dt.normalize()
for c in ("현재가", "전일종가"):
    df[c] = pd.to_numeric(df[c], errors="coerce")
df = df[(df["현재가"] > 0) & df["code"].notna()].copy()
df["code"] = df["code"].astype(str)
df = df.sort_values("ts")

days = sorted(df["d"].unique())
pos = {d: i for i, d in enumerate(days)}
g = df.groupby(["code", "d"])
p = pd.DataFrame({"open_px": g["현재가"].first(), "last_px": g["현재가"].last(),
                  "prev_close": g["전일종가"].last()}).reset_index().sort_values(["code", "d"])
p["next_prev_close"] = p.groupby("code")["prev_close"].shift(-1)
p["next_d"] = p.groupby("code")["d"].shift(-1)
p["gap_days"] = p.apply(lambda r: (pos.get(r["next_d"], np.nan) - pos[r["d"]])
                        if pd.notna(r["next_d"]) else np.nan, axis=1)
p["close"] = np.where((p["gap_days"] == 1) & (p["next_prev_close"] > 0),
                      p["next_prev_close"], p["last_px"])
p = p[(p["open_px"] > 0) & (p["prev_close"] > 0) & (p["close"] > 0)]
p["i"] = p["d"].map(pos)
p = p.sort_values(["code", "i"])
nc = p.groupby("code")["close"].shift(-1)
ni = p.groupby("code")["i"].shift(-1)
p["next_close"] = np.where((ni - p["i"]) == 1, nc, np.nan)

close_map = {(r.code, r.d): r.close for r in p.itertuples()}
snaps = {k: list(v) for k, v in df.groupby(["code", "d"])["현재가"]}

p["gap"] = (p["open_px"] / p["prev_close"] - 1) * 100
p["intra"] = (p["close"] / p["open_px"] - 1) * 100
sig = p[(p["gap"] >= 3) & (p["intra"] <= -3) & p["next_close"].notna()]
print(f"표본: {len(sig)}건 (V0 실측 재현과 동일)")


def net(e, x):
    return ((x * (1 - SELL_FEE)) / (e * (1 + BUY_FEE)) - 1) * 100


def evaluate(tp, sl):
    """tp/sl은 % 또는 None. 익일 스냅샷을 시간순으로 훑어 선터치 반영."""
    out = []
    for r in sig.itertuples():
        i = pos[r.d] + 1
        nd = days[i] if i < len(days) else None
        e = r.close
        hit = None
        if nd is not None:
            hi = e * (1 + tp / 100) if tp else None
            lo = e * (1 + sl / 100) if sl else None
            for px in snaps.get((r.code, nd), []):
                if hi and px >= hi:
                    hit = hi; break
                if lo and px <= lo:
                    hit = lo; break
        out.append(net(e, hit if hit is not None else r.next_close))
    s = pd.Series(out)
    return s.mean(), (s > 0).mean() * 100, len(s)


for label, tp, sl in [("브래킷 없음 (실측 조건)", None, None),
                      ("익절 +3%만", 3, None),
                      ("손절 -3%만", None, -3),
                      ("익절 +3% / 손절 -3% (스펙)", 3, -3),
                      ("익절 +5% / 손절 -3%", 5, -3),
                      ("손절 -5%만", None, -5)]:
    m, w, n = evaluate(tp, sl)
    print(f"  {label:<28} 평균 {m:+.2f}%  승률 {w:.1f}%  n={n}")
