"""월간 누적 엑셀에서 '수집 실패 런'의 행을 제거한다 (일회성 정비).

배경
----
data_fetcher.fetch_page가 타임아웃을 삼켜 '글 0건인 페이지'로 처리하던 버그
(2026-07-10 수정, 061f651a) 때문에, 일부 런의 게시물 수가 실제보다 크게 낮게
기록됐다. 월간 엑셀은 중복 제거 없는 누적 append라 그 행들이 그대로 남아 있고,
백테스트가 이를 '후보가 적었던 런'으로 오인한다.

판정
----
같은 날 같은 종목의 게시물 수는 줄어들 수 없다. 줄어든 경우 원인은 둘이다.
  - 네이버에서 글이 삭제됨 : 그 종목 하나만, 임의의 건수만큼
  - 페이지 수집 실패       : 그 런의 여러 종목이 동시에, 크게

따라서 아래 중 하나면 그 런 전체를 제거한다.
  - 어떤 종목이든 30% 이상 하락 (파국적)
  - 10% 이상 하락한 종목이 2개 이상 (전면적)

사용법
------
    python scratch/clean_degraded_runs.py <db-data 체크아웃 경로>            # dry-run
    python scratch/clean_degraded_runs.py <db-data 체크아웃 경로> --apply    # 실제 삭제
"""
import sys
import glob
import os
import pandas as pd

CATASTROPHIC = 0.30
SYSTEMIC_REL = 0.10
SYSTEMIC_MIN_STOCKS = 2


def posts_series(df: pd.DataFrame) -> pd.Series:
    """게시글 수 컬럼. 2026-03까지는 '당일_게시글수', 2026-05부터는 '게시물',
    2026-04는 전환기라 행마다 둘 중 하나만 채워져 있다."""
    cols = [c for c in ('게시물', '당일_게시글수') if c in df.columns]
    if not cols:
        return pd.Series([pd.NA] * len(df), index=df.index)
    s = df[cols[0]]
    for c in cols[1:]:
        s = s.fillna(df[c])
    return s


def degraded_timestamps(df: pd.DataFrame) -> set:
    """제거 대상 수집시각 집합."""
    df = df.assign(_posts=posts_series(df))
    ts_col = df['데이터_수집시각'].astype(str)
    day = ts_col.str[:10]
    bad = set()

    for d in sorted(day.unique()):
        g = df[day == d]
        g_ts = ts_col[g.index]
        seen = {}
        for ts in sorted(g_ts.unique()):
            run = g[g_ts == ts]
            worst, systemic = 0.0, 0
            for _, r in run.iterrows():
                if pd.isna(r['_posts']):
                    continue
                nm, posts = r['종목명'], int(r['_posts'])
                prev = seen.get(nm)
                if prev and posts < prev:
                    rel = 1 - posts / prev
                    worst = max(worst, rel)
                    if rel >= SYSTEMIC_REL:
                        systemic += 1
            if worst >= CATASTROPHIC or systemic >= SYSTEMIC_MIN_STOCKS:
                bad.add(ts)
            for _, r in run.iterrows():
                if not pd.isna(r['_posts']):
                    nm = r['종목명']
                    seen[nm] = max(seen.get(nm, 0), int(r['_posts']))
    return bad


def hour_key(ts: str) -> str:
    """'2026-07-10 11:11:21' → '20260710_11' (시간별 스냅샷 파일명 규칙)"""
    return ts[:4] + ts[5:7] + ts[8:10] + '_' + ts[11:13]


def fix_snapshots(root, monthly, bad, apply):
    """시간별 스냅샷은 그 시각의 마지막 런으로 덮어써진다.

    마지막 런이 오염됐으면 같은 시간대의 정상 런으로 복원하고,
    그 시간대에 정상 런이 하나도 없으면 파일을 지운다.
    (스냅샷 파일에는 수집시각 컬럼이 없어 파일명으로만 대응시킬 수 있다.)
    """
    by_hour = {}
    for ts in sorted(monthly['데이터_수집시각'].astype(str).unique()):
        by_hour.setdefault(hour_key(ts), []).append(ts)

    rebuilt = removed = 0
    for h, tss in by_hour.items():
        if tss[-1] not in bad:
            continue
        path = os.path.join(root, 'data', f'trending_integrated_{h}.xlsx')
        if not os.path.exists(path):
            continue
        healthy = [t for t in tss if t not in bad]
        if healthy:
            src = monthly[monthly['데이터_수집시각'].astype(str) == healthy[-1]]
            src = src.drop(columns=['데이터_수집시각'])
            print(f"  복원 {os.path.basename(path)}  <- {healthy[-1]} ({len(src)}행)")
            if apply:
                with pd.ExcelWriter(path, engine='openpyxl') as w:
                    src.to_excel(w, sheet_name='Trending_Stocks', index=False)
            rebuilt += 1
        else:
            print(f"  삭제 {os.path.basename(path)}  (그 시간대 전부 오염)")
            if apply:
                os.remove(path)
            removed += 1
    return rebuilt, removed


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    root = sys.argv[1]
    apply = '--apply' in sys.argv

    pattern = os.path.join(root, 'data', 'trending_integrated_[0-9][0-9][0-9][0-9]-[0-9][0-9].xlsx')
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"대상 파일 없음: {pattern}")
        sys.exit(1)

    total_runs = total_rows = 0
    all_monthly, all_bad = [], set()
    for path in files:
        df = pd.read_excel(path)
        bad = degraded_timestamps(df)
        all_monthly.append(df)
        all_bad |= bad
        if not bad:
            print(f"{os.path.basename(path):35s} 제거 대상 없음 ({len(df)}행 유지)")
            continue

        ts_col = df['데이터_수집시각'].astype(str)
        keep = df[~ts_col.isin(bad)]
        removed = len(df) - len(keep)
        total_runs += len(bad)
        total_rows += removed

        print(f"{os.path.basename(path):35s} {len(bad):3d}런 / {removed:4d}행 제거  → {len(keep)}행 유지")
        if apply:
            keep.to_excel(path, index=False)

    print()
    print("시간별 스냅샷:")
    monthly = pd.concat(all_monthly, ignore_index=True)
    rebuilt, snap_removed = fix_snapshots(root, monthly, all_bad, apply)

    print()
    print(f"{'실제 적용 완료' if apply else 'DRY-RUN (변경 없음)'}: "
          f"월간 {total_runs}런 / {total_rows}행 제거, 스냅샷 {rebuilt}개 복원 / {snap_removed}개 삭제")


if __name__ == '__main__':
    main()
