"""심9(갭소진) 배포 게이트 백테스트 — 체결 가능한 정보만 사용.

설계 문서의 실측(+2.98%)과 결정적으로 다른 점:
  실측은 '종가 기준 되밀림'으로 신호를 정의하고 종가에 진입한다고 가정했다.
  종가는 15:30에 확정되므로 그 값으로 15:00에 매수 결정을 내릴 수 없다 — 룩어헤드다.
  여기서는 신호·진입가를 모두 [14:30, 15:20) 구간의 마지막 스냅샷으로 잡는다.
  (15:20부터는 동시호가라 그 가격으로 체결할 수 없다.)

그 외 실제 심 규칙을 그대로 태운다:
  NAV 300만 · 종목당 15% · 최대 6종목 · 수수료(매수 0.015%, 매도 0.195%)
  청산은 -3% 손절 또는 익일 동일 구간(타임스탑 1일). 고정 익절 없음.

한계(엑셀에 컬럼이 없어 적용 불가):
  - 거래대금 10억 필터 미적용 → 실전 슬리피지가 여기 초과수익을 더 깎는다.
  - 시가는 그날 첫 스냅샷(09:02) 근사. 실제 시가는 2026-07-28 배선분부터 쌓인다.
  - 유니버스가 동적이라 익일 데이터가 없는 신호는 측정 불가로 제외했다(생존 편향).

데이터:
  git fetch origin db-data:db-data --force
  git show db-data:data/trending_integrated_2026-07.xlsx > scratch/ti_2026-07.xlsx
"""
import numpy as np
import pandas as pd
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.strategy.simulators import sim9_gap_fade as S

SP = os.path.dirname(__file__)
INITIAL_CASH = 3_000_000
BUY_FEE = 0.00015
SELL_FEE = 0.00015 + 0.0018
T_FROM = pd.Timestamp('14:30:00').time()
T_TO = pd.Timestamp('15:20:00').time()   # 동시호가 시작 = 체결 가능 한계

# ── 로드 ────────────────────────────────────────────────
df = pd.concat([pd.read_excel(f"{SP}/ti_2026-{m}.xlsx") for m in ("06", "07")],
               ignore_index=True)
df["ts"] = pd.to_datetime(df["데이터_수집시각"], errors="coerce")
df = df.dropna(subset=["ts"])
df["d"] = df["ts"].dt.normalize()
df["t"] = df["ts"].dt.time
for c in ("현재가", "전일종가"):
    df[c] = pd.to_numeric(df[c], errors="coerce")
df["chg"] = pd.to_numeric(df["등락률"].astype(str).str.replace('%', '', regex=False),
                          errors="coerce").fillna(0)
df = df[(df["현재가"] > 0) & df["code"].notna()].copy()
df["code"] = df["code"].astype(str)
df = df.sort_values("ts")

days = sorted(df["d"].unique())
pos = {d: i for i, d in enumerate(days)}

g = df.groupby(["code", "d"])
panel = pd.DataFrame({
    "open_px": g["현재가"].first(),      # 첫 스냅샷 ≈ 시가 (근사)
    "last_px": g["현재가"].last(),
    "prev_close": g["전일종가"].last(),
}).reset_index().sort_values(["code", "d"])
panel["next_prev_close"] = panel.groupby("code")["prev_close"].shift(-1)
panel["next_d"] = panel.groupby("code")["d"].shift(-1)
panel["gap_days"] = panel.apply(
    lambda r: (pos.get(r["next_d"], np.nan) - pos[r["d"]]) if pd.notna(r["next_d"]) else np.nan,
    axis=1)
panel["close"] = np.where((panel["gap_days"] == 1) & (panel["next_prev_close"] > 0),
                          panel["next_prev_close"], panel["last_px"])
panel = panel[(panel["open_px"] > 0) & (panel["prev_close"] > 0)]

open_map = {(r.code, r.d): r.open_px for r in panel.itertuples()}
prev_map = {(r.code, r.d): r.prev_close for r in panel.itertuples()}
close_map = {(r.code, r.d): r.close for r in panel.itertuples()}

win = df[(df["t"] >= T_FROM) & (df["t"] < T_TO)]
win_last = win.groupby(["code", "d"]).last()          # 그날 체결 가능한 마지막 관측
snaps = {k: list(v) for k, v in df.groupby(["code", "d"])["현재가"]}


def next_day(d):
    i = pos[d] + 1
    return days[i] if i < len(days) else None


def exit_price(code, d, entry_px):
    """익일 청산가. -3% 손절 선터치를 먼저 반영, 아니면 익일 동일 구간 가격,
    그것도 없으면 복원 종가. 전부 없으면 None(측정 불가)."""
    nd = next_day(d)
    if nd is None:
        return None, "미측정"
    lo = entry_px * (1 + S.STOP_PCT / 100)
    for i, px in enumerate(snaps.get((code, nd), [])):
        if px <= lo:
            # 오버나이트 보유라 익일 첫 관측이 이미 손절선 아래면 갭하락이다.
            # 그 경우 -3%에 체결될 수 없다 — 갭 난 가격에 체결된다.
            return (px if i == 0 else lo), "손절(갭하락)" if i == 0 else "손절"
    if (code, nd) in win_last.index:
        return float(win_last.loc[(code, nd), "현재가"]), "타임스탑"
    c = close_map.get((code, nd))
    if c and c > 0:
        return float(c), "타임스탑(종가복원)"
    return None, "미측정"


# ── 신호 생성 ───────────────────────────────────────────
signals = []
for (code, d), row in win_last.iterrows():
    op, pc = open_map.get((code, d)), prev_map.get((code, d))
    if not op or not pc or op <= 0 or pc <= 0:
        continue
    entry_px = float(row["현재가"])
    gap = (op / pc - 1) * 100
    intra = (entry_px / op - 1) * 100
    if gap >= S.GAP_MIN and intra <= S.INTRA_MAX:
        signals.append((d, code, row["종목명"], entry_px, gap, intra, row["chg"]))

sig_df = pd.DataFrame(signals, columns=["d", "code", "name", "entry_px", "gap", "intra", "chg"])
print(f"패널: {len(panel)}종목-일, {panel['code'].nunique()}종목, {len(days)}거래일")
print(f"신호: {len(sig_df)}건 (발생률 {len(sig_df)/max(len(panel),1)*100:.1f}%)")


def net(entry, exit_px):
    return ((exit_px * (1 - SELL_FEE)) / (entry * (1 + BUY_FEE)) - 1) * 100


# ── 1) 신호 수준 ────────────────────────────────────────
rows = []
for r in sig_df.itertuples():
    px, kind = exit_price(r.code, r.d, r.entry_px)
    rows.append((r.d, r.code, np.nan if px is None else net(r.entry_px, px), kind))
sig_res = pd.DataFrame(rows, columns=["d", "code", "net", "kind"])
meas = sig_res["net"].dropna()
print(f"\n[신호 수준] 측정 {len(meas)}건 / 측정불가 {sig_res['net'].isna().sum()}건")
print(f"  +1일 순수익 평균 {meas.mean():+.2f}%, 중앙값 {meas.median():+.2f}%, "
      f"승률 {(meas > 0).mean()*100:.1f}%")
print("  청산 유형:", sig_res["kind"].value_counts().to_dict())

# ── 2) 포트폴리오 수준 ──────────────────────────────────
measurable = {(r.d, r.code) for r in sig_res.dropna(subset=["net"]).itertuples()}
cash = INITIAL_CASH
holdings = {}
trades = []
sig_by_day = {d: sub.sort_values("chg", ascending=False) for d, sub in sig_df.groupby("d")}

for d in days:
    for code, (qty, epx, ed) in list(holdings.items()):
        px, _ = exit_price(code, ed, epx)
        if px is None:
            continue                       # 측정 불가 — 진입 단계에서 걸렀으므로 도달하지 않음
        proceeds = qty * px * (1 - SELL_FEE)
        cost = qty * epx * (1 + BUY_FEE)
        cash += proceeds
        trades.append((d, code, proceeds - cost, (proceeds / cost - 1) * 100))
        del holdings[code]

    nav = cash + sum(q * close_map.get((c, d), e) for c, (q, e, _) in holdings.items())
    target = nav * S.POSITION_WEIGHT
    for r in sig_by_day.get(d, pd.DataFrame()).itertuples():
        if len(holdings) >= S.MAX_HOLDINGS:
            break
        if r.code in holdings or (r.d, r.code) not in measurable:
            continue
        qty = int(target / r.entry_px)
        cost = qty * r.entry_px * (1 + BUY_FEE)
        if qty <= 0 or cost > cash:
            continue
        cash -= cost
        holdings[r.code] = (qty, r.entry_px, r.d)

final_nav = cash + sum(q * e for q, e, _ in holdings.values())
tr = pd.DataFrame(trades, columns=["d", "code", "pnl", "ret"])
tr["ym"] = pd.to_datetime(tr["d"]).dt.strftime("%Y-%m")
months = tr["ym"].nunique()

print(f"\n[포트폴리오 수준] 초기 {INITIAL_CASH:,}원 → 최종 {final_nav:,.0f}원 "
      f"({(final_nav/INITIAL_CASH-1)*100:+.2f}%)")
print(f"  총 거래 {len(tr)}건 / {months}개월 = 월 {len(tr)/max(months,1):.1f}건")
print(f"  거래당 평균 순수익 {tr['ret'].mean():+.2f}%, 승률 {(tr['ret'] > 0).mean()*100:.1f}%")
print("  월별 거래수:", tr["ym"].value_counts().sort_index().to_dict())

# ── 3) 배포 게이트 ──────────────────────────────────────
m, w, f = tr["ret"].mean(), (tr["ret"] > 0).mean() * 100, len(tr) / max(months, 1)
g1, g2, g3 = m >= 2.0, w >= 55, f <= 25
print("\n[배포 게이트]")
print(f"  +1일 순수익 >= +2.0% : {m:+.2f}%  {'PASS' if g1 else 'FAIL'}")
print(f"  승률 >= 55%          : {w:.1f}%  {'PASS' if g2 else 'FAIL'}")
print(f"  월 거래수 <= 25건    : {f:.1f}건  {'PASS' if g3 else 'FAIL'}")
print(f"  → {'전체 통과' if (g1 and g2 and g3) else '미통과 (실전 승격 보류)'}")

# ── 4) 분포 점검 — 평균이 소수 극단값에 끌려가는지 ────────
print("\n[분포 점검]")
q = meas.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
print("  분위수:", {f"{int(k*100)}%": f"{v:+.1f}" for k, v in q.items()})
top = sig_res.dropna(subset=["net"]).sort_values("net", ascending=False).head(8)
name_map = {(r.d, r.code): (r.name, r.entry_px) for r in sig_df.itertuples()}
for r in top.itertuples():
    nm, epx = name_map.get((r.d, r.code), ("?", 0))
    nd = next_day(r.d)
    px, kind = exit_price(r.code, r.d, epx)
    print(f"  {pd.Timestamp(r.d).date()} {nm}({r.code}) {r.net:+.1f}%  "
          f"진입 {epx:,.0f} → 청산 {px:,.0f} ({kind}, 익일 {pd.Timestamp(nd).date() if nd else '-'})")
print(f"  상위 5건 제외 시 평균: {meas.sort_values().iloc[:-5].mean():+.2f}%")
