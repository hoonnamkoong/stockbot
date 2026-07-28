"""심9 개선 — 파라미터 탐색이 아니라 손실의 구조를 먼저 본다.

전제: 진입은 [14:30, 15:20) 마지막 스냅샷(체결 가능), 청산은 익일 같은 구간.
      손절은 익일 첫 관측이 이미 손절선 아래면 그 가격에 체결(갭하락 현실 반영).
      = backtest_sim9.py와 동일한 측정 방식.

표본이 42거래일·측정 110건뿐이라 슬라이스별 평균은 오차가 크다. 그래서 모든
후보 필터를 6월/7월로 쪼개 양쪽에서 같은 방향인지 확인한다. 한쪽에서만
좋아지는 필터는 채택하지 않는다.
"""
import numpy as np
import pandas as pd
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.strategy.simulators import sim9_gap_fade as S

SP = os.path.dirname(__file__)
BUY_FEE, SELL_FEE = 0.00015, 0.00015 + 0.0018
T_FROM, T_TO = pd.Timestamp('14:30:00').time(), pd.Timestamp('15:20:00').time()

ti = pd.concat([pd.read_excel(f"{SP}/ti_2026-{m}.xlsx") for m in ("06", "07")],
               ignore_index=True)
ti["ts"] = pd.to_datetime(ti["데이터_수집시각"], errors="coerce")
ti = ti.dropna(subset=["ts"])
ti["d"] = ti["ts"].dt.normalize()
ti["t"] = ti["ts"].dt.time
for c in ("현재가", "전일종가", "게시물"):
    ti[c] = pd.to_numeric(ti.get(c), errors="coerce")
ti = ti[(ti["현재가"] > 0) & ti["code"].notna()].copy()
ti["code"] = ti["code"].astype(str)
ti = ti.sort_values("ts")

days = sorted(ti["d"].unique())
pos = {d: i for i, d in enumerate(days)}

g = ti.groupby(["code", "d"])
panel = pd.DataFrame({
    "open_px": g["현재가"].first(),
    "day_hi": g["현재가"].max(),      # 스냅샷 기준 일중 고가(근사)
    "day_lo": g["현재가"].min(),      # 스냅샷 기준 일중 저가(근사)
    "last_px": g["현재가"].last(),
    "prev_close": g["전일종가"].last(),
    "buzz": g["게시물"].max(),
    "snaps": g["현재가"].count(),
}).reset_index().sort_values(["code", "d"])
panel["next_prev_close"] = panel.groupby("code")["prev_close"].shift(-1)
panel["next_d"] = panel.groupby("code")["d"].shift(-1)
panel["gap_days"] = panel.apply(lambda r: (pos.get(r["next_d"], np.nan) - pos[r["d"]])
                                if pd.notna(r["next_d"]) else np.nan, axis=1)
panel["close"] = np.where((panel["gap_days"] == 1) & (panel["next_prev_close"] > 0),
                          panel["next_prev_close"], panel["last_px"])
panel = panel[(panel["open_px"] > 0) & (panel["prev_close"] > 0)]

meta = {(r.code, r.d): r for r in panel.itertuples()}
close_map = {(r.code, r.d): r.close for r in panel.itertuples()}
snaps = {k: list(v) for k, v in ti.groupby(["code", "d"])["현재가"]}
win = ti[(ti["t"] >= T_FROM) & (ti["t"] < T_TO)]
win_last = win.groupby(["code", "d"])["현재가"].last().to_dict()

# 국면: 리포트 엑셀의 날짜별 Market Regime / Bull Score
regime, bull = {}, {}
try:
    mr = pd.concat([pd.read_excel(f"{SP}/mr_2026-{m}.xlsx") for m in ("06", "07")],
                   ignore_index=True)
    mr["d"] = pd.to_datetime(mr["DateTime"], errors="coerce").dt.normalize()
    for d, sub in mr.dropna(subset=["d"]).groupby("d"):
        v = sub["Market Regime"].dropna()
        if len(v):
            regime[d] = v.iloc[-1]
        b = pd.to_numeric(sub.get("Bull Score"), errors="coerce").dropna()
        if len(b):
            bull[d] = b.iloc[-1]
except Exception as e:
    print(f"[국면 데이터 없음: {e}]")


def next_day(d):
    i = pos[d] + 1
    return days[i] if i < len(days) else None


def exit_net(code, d, entry):
    """익일 청산 순수익 %. 갭하락 손절은 갭 난 가격에 체결. 측정 불가면 None."""
    nd = next_day(d)
    if nd is None:
        return None
    lo = entry * (1 + S.STOP_PCT / 100)
    px = None
    for i, p in enumerate(snaps.get((code, nd), [])):
        if p <= lo:
            px = p if i == 0 else lo
            break
    if px is None:
        px = win_last.get((code, nd)) or close_map.get((code, nd))
    if not px or px <= 0:
        return None
    return ((px * (1 - SELL_FEE)) / (entry * (1 + BUY_FEE)) - 1) * 100


# ── 신호 + 특성 ──────────────────────────────────────────
rows = []
for (code, d), entry in win_last.items():
    m = meta.get((code, d))
    if m is None or m.snaps < 3:
        continue
    gap = (m.open_px / m.prev_close - 1) * 100
    intra = (entry / m.open_px - 1) * 100
    if not (gap >= S.GAP_MIN and intra <= S.INTRA_MAX):
        continue
    net = exit_net(code, d, entry)
    if net is None:
        continue
    rng = m.day_hi - m.day_lo
    rows.append({
        "code": code, "d": d, "ym": pd.Timestamp(d).strftime("%Y-%m"),
        "gap": gap, "intra": intra, "net": net, "entry": entry,
        # 진입 시점이 그날 변동폭의 어디인가 (0=저가, 1=고가)
        "range_pos": (entry - m.day_lo) / rng if rng > 0 else 0.5,
        # 저가 대비 얼마나 되돌아왔나
        "bounce": (entry / m.day_lo - 1) * 100 if m.day_lo > 0 else 0.0,
        "day_range": rng / m.open_px * 100 if m.open_px > 0 else 0.0,
        "buzz": m.buzz if not pd.isna(m.buzz) else 0,
        "regime": regime.get(d, "?"),
        "bull": bull.get(d, np.nan),
    })
df = pd.DataFrame(rows)
print(f"측정 가능한 신호 {len(df)}건 (6월 {sum(df.ym=='2026-06')} / 7월 {sum(df.ym=='2026-07')})")
print(f"전체 평균 {df.net.mean():+.2f}%, 승률 {(df.net>0).mean()*100:.1f}%\n")


def slice_by(name, series, bins, labels=None):
    print(f"■ {name}")
    cut = pd.cut(series, bins, labels=labels)
    for lv, sub in df.groupby(cut, observed=True):
        if len(sub) < 5:
            continue
        s6, s7 = sub[sub.ym == '2026-06'], sub[sub.ym == '2026-07']
        print(f"   {str(lv):<14} n={len(sub):>3}  평균 {sub.net.mean():+6.2f}%  "
              f"승률 {(sub.net>0).mean()*100:4.1f}%   "
              f"[6월 {s6.net.mean():+5.2f}%({len(s6)}) / 7월 {s7.net.mean():+5.2f}%({len(s7)})]")
    print()


slice_by("갭 크기", df.gap, [3, 4, 5, 7, 100])
slice_by("되밀림 깊이", df.intra, [-100, -8, -6, -4, -3])
slice_by("진입 시점의 일중 위치 (0=저가 근처, 1=고가 근처)", df.range_pos, [0, .2, .4, .6, 1.01])
slice_by("일중 변동폭 (고가-저가)/시가 %", df.day_range, [0, 5, 8, 12, 100])
slice_by("저가 대비 반등률 %", df.bounce, [-1, 0.5, 2, 5, 100])
slice_by("버즈(게시물수)", df.buzz, [0, 100, 300, 1000, 100000])

if df.regime.nunique() > 1:
    print("■ 시장 국면 (Sim0)")
    for lv, sub in df.groupby("regime"):
        if len(sub) < 5:
            continue
        print(f"   {lv:<14} n={len(sub):>3}  평균 {sub.net.mean():+6.2f}%  "
              f"승률 {(sub.net>0).mean()*100:4.1f}%")
    print()

print("■ 손실 상위 10건의 특성")
for r in df.nsmallest(10, "net").itertuples():
    print(f"   {pd.Timestamp(r.d).date()} {r.code} {r.net:+6.1f}%  갭{r.gap:+5.1f} "
          f"장중{r.intra:+5.1f} 일중위치{r.range_pos:.2f} 변동폭{r.day_range:4.1f}% 버즈{int(r.buzz)}")


# ── 후보 필터 조합 (사전 지정 6개만. 표본을 뒤져 고르지 않는다) ──────
print("\n" + "=" * 96)
print("후보 필터 — 6월/7월 양쪽에서 같은 방향인 것만 채택한다")
print("=" * 96)
MONTHS = 42 / 21  # 42거래일 ≈ 2개월

cands = [
    ("현행 (갭>=3, 장중<=-3)",            lambda x: x.index == x.index),
    ("R: 일중위치<=0.2 (저가 근처 마감)",  lambda x: x.range_pos <= 0.2),
    ("R + 갭>=7",                         lambda x: (x.range_pos <= 0.2) & (x.gap >= 7)),
    ("R + 되밀림<=-6",                    lambda x: (x.range_pos <= 0.2) & (x.intra <= -6)),
    ("R + 갭>=7 + 되밀림<=-6",             lambda x: (x.range_pos <= 0.2) & (x.gap >= 7) & (x.intra <= -6)),
    ("저가대비 반등 0.5~2%",               lambda x: (x.bounce > 0.5) & (x.bounce <= 2)),
    ("R + 버즈<=300",                     lambda x: (x.range_pos <= 0.2) & (x.buzz <= 300)),
]

print(f"{'필터':<30}{'n':>4}{'평균%':>8}{'승률%':>7}{'월거래':>7}   {'6월':>14}{'7월':>14}  게이트")
print("-" * 96)
for label, fn in cands:
    sub = df[fn(df)]
    if len(sub) < 5:
        print(f"{label:<30}{len(sub):>4}  표본 부족")
        continue
    s6, s7 = sub[sub.ym == '2026-06'], sub[sub.ym == '2026-07']
    m, w, freq = sub.net.mean(), (sub.net > 0).mean() * 100, len(sub) / MONTHS
    gate = ("O" if m >= 2.0 else "X") + ("O" if w >= 55 else "X") + ("O" if freq <= 25 else "X")
    consistent = "일치" if (len(s6) >= 5 and len(s7) >= 5
                          and np.sign(s6.net.mean()) == np.sign(s7.net.mean())) else "확인불가"
    print(f"{label:<30}{len(sub):>4}{m:>+7.2f}%{w:>6.1f}%{freq:>6.1f}건   "
          f"{s6.net.mean():>+7.2f}%({len(s6):>2}){s7.net.mean():>+7.2f}%({len(s7):>2})  {gate} {consistent}")

print("\n[참고] 일중위치는 실전에서 KIS inquire-price의 stck_hgpr/stck_lwpr로 계산된다")
print("       (w52_hgpr을 읽는 바로 그 응답 — 추가 네트워크 콜 0)")


# ── 채택 후보의 포트폴리오 수준 검증 ────────────────────
print("\n" + "=" * 96)
print("채택 후보 포트폴리오 검증 (NAV 300만·종목당 15%·최대 6종목·수수료 반영)")
print("=" * 96)
INITIAL = 3_000_000

def portfolio(mask_fn, label):
    sub = df[mask_fn(df)].sort_values("d")
    cash, holds, trades = INITIAL, {}, []
    by_day = {d: s for d, s in sub.groupby("d")}
    for d in days:
        for code, (qty, epx, ret) in list(holds.items()):
            cash += qty * epx * (1 + ret / 100)
            trades.append(ret)
            del holds[code]
        nav = cash
        for r in by_day.get(d, pd.DataFrame()).itertuples():
            if len(holds) >= S.MAX_HOLDINGS or r.code in holds:
                continue
            qty = int(nav * S.POSITION_WEIGHT / r.entry)
            cost = qty * r.entry
            if qty <= 0 or cost > cash:
                continue
            cash -= cost
            holds[r.code] = (qty, r.entry, r.net)
    final = cash + sum(q * e for q, e, _ in holds.values())
    srt = sorted(trades, reverse=True)
    ex5 = sum(srt[5:]) / len(srt[5:]) if len(srt) > 5 else float('nan')
    print(f"{label:<28} 거래 {len(trades):>3}건  거래당 {np.mean(trades):+5.2f}%  "
          f"승률 {np.mean([t>0 for t in trades])*100:4.1f}%  "
          f"NAV {(final/INITIAL-1)*100:+7.2f}%  상위5제외 {ex5:+5.2f}%")

portfolio(lambda x: x.index == x.index, "현행")
portfolio(lambda x: x.range_pos <= 0.2, "R만")
portfolio(lambda x: (x.range_pos <= 0.2) & (x.gap >= 7) & (x.intra <= -6), "R+갭7+되밀림6 (채택안)")
portfolio(lambda x: (x.range_pos <= 0.2) & (x.buzz <= 300), "R+버즈300 (참고)")
