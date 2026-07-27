"""D-1(돈치안 채널 돌파) vs D-5(갭/장중 분해) 실측 비교.

데이터: trending_integrated 2026-06 + 2026-07 월별 스냅샷 (41거래일, 231종목).
- 종가: 다음 거래일 행의 '전일종가' (진짜 종가). 없으면 그날 마지막 스냅샷 가격.
- 시가: 그날 첫 스냅샷(09:02) 가격 — 진짜 시가가 아니라 근사.
같은 유니버스·같은 기간·같은 forward return 측정으로 비교한다.
"""
import numpy as np
import pandas as pd

# 월별 엑셀 위치. db-data에서 받아온다:
#   git fetch origin db-data:db-data --force
#   git show db-data:data/trending_integrated_2026-07.xlsx > scratch/ti_2026-07.xlsx
SP = "scratch"

df = pd.concat([pd.read_excel(f"{SP}/ti_2026-{m}.xlsx") for m in ("06", "07")],
               ignore_index=True)
df["ts"] = pd.to_datetime(df["데이터_수집시각"], errors="coerce")
df = df.dropna(subset=["ts"])
df["d"] = df["ts"].dt.normalize()
for c in ("현재가", "전일종가"):
    df[c] = pd.to_numeric(df[c], errors="coerce")
df = df[(df["현재가"] > 0) & df["code"].notna()]
df["code"] = df["code"].astype(str)

# ── 일별 패널 ────────────────────────────────────────────
df = df.sort_values("ts")
g = df.groupby(["code", "d"])
panel = pd.DataFrame({
    "open_px": g["현재가"].first(),      # 첫 스냅샷 ≈ 시가 (근사)
    "last_px": g["현재가"].last(),       # 마지막 스냅샷
    "prev_close": g["전일종가"].last(),
}).reset_index().sort_values(["code", "d"])

# 종가 복원: 다음 거래일 행의 prev_close가 진짜 그날 종가
panel["next_prev_close"] = panel.groupby("code")["prev_close"].shift(-1)
panel["next_d"] = panel.groupby("code")["d"].shift(-1)
trading_days = sorted(panel["d"].unique())
pos = {d: i for i, d in enumerate(trading_days)}
panel["gap_days"] = panel.apply(
    lambda r: (pos.get(r["next_d"], np.nan) - pos[r["d"]]) if pd.notna(r["next_d"]) else np.nan,
    axis=1)
ok = (panel["gap_days"] == 1) & (panel["next_prev_close"] > 0)
panel["close"] = np.where(ok, panel["next_prev_close"], panel["last_px"])

# 복원 정확도 점검
chk = panel[ok]
err = (chk["last_px"] / chk["next_prev_close"] - 1).abs()
print(f"[종가 복원] 다음날 전일종가로 확정 {ok.sum()}/{len(panel)}건 "
      f"({ok.mean()*100:.1f}%)")
print(f"  마지막 스냅샷과의 오차: 중앙값 {err.median()*100:.2f}%, "
      f"|오차|<0.5% 비율 {(err < 0.005).mean()*100:.1f}%")

panel = panel[(panel["close"] > 0) & (panel["prev_close"] > 0) & (panel["open_px"] > 0)]

# ── forward return (거래일 기준) ─────────────────────────
panel["i"] = panel["d"].map(pos)
panel = panel.sort_values(["code", "i"])
for k in (1, 3, 5):
    nxt = panel.groupby("code")["close"].shift(-k)
    ni = panel.groupby("code")["i"].shift(-k)
    valid = (ni - panel["i"]) == k
    panel[f"fwd{k}"] = np.where(valid, nxt / panel["close"] - 1, np.nan) * 100


def summarize(name, mask, base_mask=None):
    sub = panel[mask]
    rows = []
    for k in (1, 3, 5):
        v = sub[f"fwd{k}"].dropna()
        if len(v) < 15:
            rows.append((k, len(v), np.nan, np.nan))
            continue
        rows.append((k, len(v), v.mean(), (v > 0).mean() * 100))
    print(f"\n■ {name}  (신호 {mask.sum()}건 / 전체 {len(panel)}건, "
          f"발생률 {mask.mean()*100:.1f}%)")
    print(f"   {'기간':>4}{'표본':>7}{'평균수익%':>11}{'승률%':>8}{'vs기저':>9}")
    for k, n, m, w in rows:
        b = panel[f"fwd{k}"].dropna().mean() if base_mask is None else \
            panel[base_mask][f"fwd{k}"].dropna().mean()
        d = "" if np.isnan(m) else f"{m - b:+.2f}"
        print(f"   +{k}일{n:>7}{m:>11.2f}{w:>8.1f}{d:>9}")
    return rows


print(f"\n패널: {len(panel)}행, {panel['code'].nunique()}종목, "
      f"{panel['d'].nunique()}거래일")
for k in (1, 3, 5):
    v = panel[f"fwd{k}"].dropna()
    print(f"  기저 +{k}일: 표본 {len(v)}, 평균 {v.mean():+.2f}%, 승률 {(v>0).mean()*100:.1f}%")

# ── D-1: 돈치안 20일 채널 돌파 ───────────────────────────
N = 20
panel["ch_high"] = (panel.groupby("code")["close"]
                    .transform(lambda s: s.shift(1).rolling(N, min_periods=N).max()))
d1 = (panel["close"] > panel["ch_high"]) & panel["ch_high"].notna()
summarize(f"D-1 돈치안 {N}일 채널 돌파", d1)

# 참고: 10일 채널 (이력이 짧아 표본 확보용)
panel["ch_high10"] = (panel.groupby("code")["close"]
                      .transform(lambda s: s.shift(1).rolling(10, min_periods=10).max()))
d1b = (panel["close"] > panel["ch_high10"]) & panel["ch_high10"].notna()
summarize("D-1b 돈치안 10일 채널 돌파", d1b)

# ── D-5: 갭 / 장중 분해 ──────────────────────────────────
panel["ovn"] = (panel["open_px"] / panel["prev_close"] - 1) * 100   # 갭(근사)
panel["itd"] = (panel["close"] / panel["open_px"] - 1) * 100        # 장중

print(f"\n[분해] 갭 평균 {panel['ovn'].mean():+.2f}%, "
      f"장중 평균 {panel['itd'].mean():+.2f}%")
cc = panel[["ovn", "itd"]].dropna()
print(f"  갭 vs 당일 장중 상관: {cc['ovn'].corr(cc['itd']):+.3f}")
nxt_itd = panel.groupby("code")["itd"].shift(-1)
m = panel["ovn"].notna() & nxt_itd.notna()
print(f"  갭 vs 익일 장중 상관: {panel.loc[m,'ovn'].corr(nxt_itd[m]):+.3f}  "
      f"(Lou-Polk-Skouras 예측: 음(-))")

summarize("D-5a 갭상승 지속 (갭>+2% & 장중>0)",
          (panel["ovn"] > 2) & (panel["itd"] > 0))
summarize("D-5b 갭소진 (갭>+2% & 장중<0)",
          (panel["ovn"] > 2) & (panel["itd"] < 0))
summarize("D-5c 장중강세 (갭<0 & 장중>+2%)",
          (panel["ovn"] < 0) & (panel["itd"] > 2))
summarize("D-5d 갭하락 반등 (갭<-2% & 장중>0)",
          (panel["ovn"] < -2) & (panel["itd"] > 0))
