"""심9: 실제로 체결 가능한 정보만으로 알파가 남는가?

문제 인식:
  실측(+2.98%)의 진입 신호는 '종가 기준 장중 되밀림'으로 정의됐다. 종가는 15:30에
  확정되므로 그 값으로 매수 결정을 내릴 수 없다 — 룩어헤드다.
  체결 가능한 마지막 시점은 동시호가 직전(~15:20)이다.

여기서는 진입가·신호를 모두 [T, 15:20) 구간의 마지막 스냅샷으로 통일하고,
청산도 익일 같은 구간의 스냅샷으로 잡는다(익일 종가 근처 청산의 현실적 대응물).
그 위에서 갭·되밀림 임계 격자를 다시 훑는다.
"""
import numpy as np
import pandas as pd
import os

SP = os.path.dirname(__file__)
BUY_FEE, SELL_FEE = 0.00015, 0.00015 + 0.0018
CUTOFF = pd.Timestamp('15:20:00').time()   # 동시호가 시작 = 체결 가능 한계

df = pd.concat([pd.read_excel(f"{SP}/ti_2026-{m}.xlsx") for m in ("06", "07")],
               ignore_index=True)
df["ts"] = pd.to_datetime(df["데이터_수집시각"], errors="coerce")
df = df.dropna(subset=["ts"])
df["d"] = df["ts"].dt.normalize()
df["t"] = df["ts"].dt.time
for c in ("현재가", "전일종가"):
    df[c] = pd.to_numeric(df[c], errors="coerce")
df = df[(df["현재가"] > 0) & df["code"].notna()].copy()
df["code"] = df["code"].astype(str)
df = df.sort_values("ts")

days = sorted(df["d"].unique())
pos = {d: i for i, d in enumerate(days)}

g = df.groupby(["code", "d"])
base = pd.DataFrame({
    "open_px": g["현재가"].first(),
    "prev_close": g["전일종가"].last(),
    "last_px": g["현재가"].last(),
}).reset_index()
base = base[(base["open_px"] > 0) & (base["prev_close"] > 0)]

# 복원 종가 (비교용)
b = base.sort_values(["code", "d"])
b["next_prev_close"] = b.groupby("code")["prev_close"].shift(-1)
b["next_d"] = b.groupby("code")["d"].shift(-1)
b["gap_days"] = b.apply(lambda r: (pos.get(r["next_d"], np.nan) - pos[r["d"]])
                        if pd.notna(r["next_d"]) else np.nan, axis=1)
b["close"] = np.where((b["gap_days"] == 1) & (b["next_prev_close"] > 0),
                      b["next_prev_close"], b["last_px"])
close_map = {(r.code, r.d): r.close for r in b.itertuples()}
open_map = {(r.code, r.d): r.open_px for r in b.itertuples()}
prev_map = {(r.code, r.d): r.prev_close for r in b.itertuples()}


def window_price(start_time):
    """[start_time, 15:20) 구간의 마지막 스냅샷 가격. {(code,d): px}"""
    w = df[(df["t"] >= start_time) & (df["t"] < CUTOFF)]
    return w.groupby(["code", "d"])["현재가"].last().to_dict()


def next_d(d):
    i = pos[d] + 1
    return days[i] if i < len(days) else None


def net(entry, exit_px):
    return ((exit_px * (1 - SELL_FEE)) / (entry * (1 + BUY_FEE)) - 1) * 100


def run(start_time, gap_min, intra_max, exit_mode):
    px = window_price(start_time)
    rets, n_sig = [], 0
    for (code, d), entry in px.items():
        op, pc = open_map.get((code, d)), prev_map.get((code, d))
        if not op or not pc:
            continue
        gap = (op / pc - 1) * 100
        intra = (entry / op - 1) * 100
        if not (gap >= gap_min and intra <= intra_max):
            continue
        n_sig += 1
        nd = next_d(d)
        if nd is None:
            continue
        if exit_mode == "window":
            x = px.get((code, nd)) or close_map.get((code, nd))
        else:
            x = close_map.get((code, nd))
        if x and x > 0:
            rets.append(net(entry, x))
    r = pd.Series(rets)
    return n_sig, len(r), (r.mean() if len(r) else np.nan), \
        ((r > 0).mean() * 100 if len(r) else np.nan)


T_OPTS = [(pd.Timestamp('14:30:00').time(), "14:30~"),
          (pd.Timestamp('15:00:00').time(), "15:00~")]

for t, tlabel in T_OPTS:
    for exit_mode in ("window", "close"):
        exlabel = "익일 동일구간 청산" if exit_mode == "window" else "익일 복원종가 청산"
        print(f"\n■ 진입 {tlabel} 마지막 스냅샷 (15:20 이전) / {exlabel}")
        print(f"   {'갭>=':>6}" + "".join(f"{f'장중<={-i}%':>22}" for i in (2, 3, 4, 5)))
        for gm in (2, 3, 4, 5, 7):
            cells = []
            for im in (-2, -3, -4, -5):
                n_sig, n, m, w = run(t, gm, im, exit_mode)
                cells.append(f"{m:+.2f}% ({w:.0f}%, n={n})" if n else "  -")
            print(f"   {gm:>5}%" + "".join(f"{c:>22}" for c in cells))

# 참고: 되밀림 조건 없이 갭만 (되밀림이 정말 주신호인가)
print("\n[참고] 되밀림 조건 없이 갭만 (진입 15:00~ 마지막 스냅샷, 익일 동일구간 청산)")
t = pd.Timestamp('15:00:00').time()
for gm in (0, 2, 3, 5):
    n_sig, n, m, w = run(t, gm, 99, "window")
    print(f"   갭>={gm}%: 평균 {m:+.2f}%, 승률 {w:.1f}%, n={n}")


# ── 동시호가 실행 모델 ───────────────────────────────────
# 한국 시장은 15:20~15:30 종가 동시호가에 시장가를 넣으면 단일가(=종가)에 체결된다.
# 즉 '15:18 스냅샷으로 판단 → 종가에 체결'은 룩어헤드가 아니다.
print("\n\n■ 동시호가 실행 모델: 신호=15:18 스냅샷 / 체결=당일 종가 / 청산=익일 종가")


def run_auction(start_time, gap_min, intra_max):
    px = window_price(start_time)
    rets, n_sig = [], 0
    for (code, d), snap in px.items():
        op, pc = open_map.get((code, d)), prev_map.get((code, d))
        cl = close_map.get((code, d))
        if not op or not pc or not cl:
            continue
        gap = (op / pc - 1) * 100
        intra = (snap / op - 1) * 100          # 판단은 스냅샷으로
        if not (gap >= gap_min and intra <= intra_max):
            continue
        n_sig += 1
        nd = next_d(d)
        x = close_map.get((code, nd)) if nd else None
        if x and x > 0:
            rets.append(net(cl, x))            # 체결은 종가로
    r = pd.Series(rets)
    return n_sig, len(r), (r.mean() if len(r) else np.nan), \
        ((r > 0).mean() * 100 if len(r) else np.nan)


t = pd.Timestamp('14:30:00').time()
print(f"   {'갭>=':>6}" + "".join(f"{f'장중<={-i}%':>22}" for i in (2, 3, 4, 5)))
for gm in (2, 3, 4, 5, 7):
    cells = []
    for im in (-2, -3, -4, -5):
        n_sig, n, m, w = run_auction(t, gm, im)
        cells.append(f"{m:+.2f}% ({w:.0f}%, n={n})" if n else "  -")
    print(f"   {gm:>5}%" + "".join(f"{c:>22}" for c in cells))

# 동시호가 구간에서 얼마나 더 밀리는가 (이 전략의 알파 원천 점검)
t_px = window_price(t)
moves = []
for (code, d), snap in t_px.items():
    cl = close_map.get((code, d))
    op, pc = open_map.get((code, d)), prev_map.get((code, d))
    if not cl or not op or not pc:
        continue
    if (op / pc - 1) * 100 >= 3 and (snap / op - 1) * 100 <= -3:
        moves.append((cl / snap - 1) * 100)
mv = pd.Series(moves)
print(f"\n[동시호가 구간 이동] 신호 종목의 (종가/15:18가 - 1): "
      f"평균 {mv.mean():+.2f}%, 중앙값 {mv.median():+.2f}%, n={len(mv)}")
