# -*- coding: utf-8 -*-
"""국면 관측 충분성 리포트 — "언제 학습을 시작하나"에 답한다.

읽기 전용이다. 아무 파일도 쓰지 않는다.

목표 모델은 30분 앞 장중 breadth 포캐스트다. 승격 기준은
docs/superpowers/specs/2026-08-17-regime-observation-accumulation-design.md §7.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategy.regime_observations import OBS_HEADER  # noqa: E402
from src.strategy.regime_observations import load_all_observations  # noqa: E402

HORIZON_MIN = 30
TOL_MIN = 5

# §7의 하한: 학습 40일 + 검증 5일 × 4회.
MIN_TRADING_DAYS = 60

_BUCKETS = (('09~10시', 9, 10), ('10~12시', 10, 12), ('12~15시', 12, 24))


def _ts(row):
    return datetime.strptime(row['ts'], '%Y-%m-%d %H:%M')


def pair_observations(rows, horizon_min=HORIZON_MIN, tol_min=TOL_MIN):
    """(t, t+지평) 쌍. 같은 거래일만, 지평에 가장 가까운 관측 하나.

    실제 격자는 09:01, 09:13, 09:25처럼 11~12분 간격이라 정확히 +30분은 없다.
    허용오차 안에서 가장 가까운 것을 고른다.

    날짜를 넘지 않는다 — 15:20의 30분 뒤는 장이 끝난 뒤이고, 다음날 09:00과
    이으면 오버나이트 수익이 장중 신호로 둔갑한다.
    """
    ordered = sorted(rows, key=lambda r: r['ts'])
    stamps = [_ts(r) for r in ordered]
    pairs = []
    for i, base in enumerate(stamps):
        best, best_gap = None, None
        for j in range(i + 1, len(stamps)):
            if ordered[j]['ts'][:10] != ordered[i]['ts'][:10]:
                break
            delta = (stamps[j] - base).total_seconds() / 60.0
            if delta > horizon_min + tol_min:
                break
            gap = abs(delta - horizon_min)
            if gap <= tol_min and (best_gap is None or gap < best_gap):
                best, best_gap = j, gap
        if best is not None:
            pairs.append((ordered[i], ordered[best]))
    return pairs


def naive_mae(pairs):
    """기준선 ①: 30분 뒤 breadth ≈ 지금 breadth."""
    if not pairs:
        return None
    errs = [abs(b['breadth'] - a['breadth']) for a, b in pairs]
    return round(sum(errs) / len(errs), 3)


def column_coverage(rows):
    """열별 채움률. 결측을 0으로 세지 않기 위해 명시적으로 센다."""
    if not rows:
        return {}
    keys = ['ts'] + [c for c in OBS_HEADER if c != 'ts_kst']
    out = {}
    for key in keys:
        filled = sum(1 for r in rows if r.get(key) is not None)
        out[key] = round(filled / len(rows), 3)
    return out


def _bucket(row):
    hour = int(row['ts'][11:13])
    for label, lo, hi in _BUCKETS:
        if lo <= hour < hi:
            return label
    return None


def main():
    rows = load_all_observations('data')
    if not rows:
        print('관측 이력이 없다. data/regime_observations*.csv 를 확인하라.')
        return 1

    dates = sorted({r['ts'][:10] for r in rows})
    print('=' * 60)
    print(f"거래일 {len(dates)}일 / {len(rows)}행   {dates[0]} ~ {dates[-1]}")
    print(f"§7 하한 {MIN_TRADING_DAYS}거래일까지 남은 일수: {max(0, MIN_TRADING_DAYS - len(dates))}")

    print('-' * 60)
    print('열별 채움률')
    for key, ratio in column_coverage(rows).items():
        bar = '#' * int(ratio * 20)
        print(f"  {key:<12} {ratio * 100:5.1f}%  {bar}")

    pairs = pair_observations(rows)
    print('-' * 60)
    print(f"유효 (관측, 라벨) 쌍: {len(pairs)}   (지평 {HORIZON_MIN}분, 허용오차 ±{TOL_MIN}분)")
    print('  전체 행에서 이만큼만 학습에 쓸 수 있다 — 장 마감 직전 관측과 결측 슬롯이 빠진다.')

    mae = naive_mae(pairs)
    print('-' * 60)
    if mae is None:
        print('나이브 기준선 MAE: 측정 불가 (쌍이 없다)')
    else:
        print(f"나이브 기준선 MAE (현재값 유지): {mae:.3f}p")
        for label, _, _ in _BUCKETS:
            sub = [(a, b) for a, b in pairs if _bucket(a) == label]
            sub_mae = naive_mae(sub)
            got = '측정 불가' if sub_mae is None else f"{sub_mae:6.3f}p"
            print(f"    {label}  n={len(sub):<5} {got}")
        print('  모델은 이 값을 이겨야 의미가 있다. 이미 작으면 이길 여지가 없다는 뜻이고,')
        print('  그건 표본을 더 쌓아도 변하지 않는다.')
    print('=' * 60)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
