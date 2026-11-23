# -*- coding: utf-8 -*-
"""국면 채점 — "이 단계가 무엇을 맞히는가"를 숫자로 낸다.

    python3 scripts/score_regime.py [채점표.csv]

2026-11-23에 "시장 판단 정확도는 확인했어?"라는 질문을 받고 79일을 **손으로**
재생해야 했다. 재는 루틴이 없었기 때문이다. 이 스크립트가 그 자리를 메운다.

채점표(`data/regime6_scorecard.csv`)는 확정된 하루마다 한 줄씩 쌓인다
(`src/strategy/regime_scorecard.py`). 거기 `ret1`(그날의 등가중 일간수익률)이
들어 있어서 임의 구간의 누적수익률도 실현변동성도 여기서 복원된다 — 종가 CSV는
100행 롤링이라 지난 날을 되계산할 수 없다.

**읽는 법**: 이 레포는 "국면은 수익률을 예측하지 못한다"를 이미 세 번 확인했다
(지수별 11,988검정 / 선행 5,085검정 / 전환점 450검정, 통과 0~1건). 그래서 수익률
칸에 단조성이 없는 것은 결함이 아니라 **예상된 결과**다. 변동성 칸이 단조로우면
그건 문헌과 맞는다(변동성은 군집성으로 예측된다).

표본이 작을 때 숫자를 믿지 않도록 n을 항상 같이 찍는다.
"""
import csv
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.regime_scorecard import FILENAME  # noqa: E402

LABEL = {'-2': '매우하락', '-1': '하락', '0': '횡보', '1': '상승', '2': '매우상승'}
HORIZONS = (1, 5, 10)
MIN_N = 5          # 이보다 적으면 수치를 내되 '표본 부족'을 붙인다


def load(path):
    """날짜순 (date, level, ret1) 목록. ret1이 없는 날은 뺀다 — 지어내지 않는다."""
    out = []
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            try:
                out.append((r['date'], str(r['level']), float(r['ret1'])))
            except (KeyError, TypeError, ValueError):
                continue
    return sorted(out)


def forward(rets, i, h):
    """i일 **다음날부터** h일 누적수익률(%). 판정일 자신은 넣지 않는다."""
    if i + h >= len(rets):
        return None
    acc = 1.0
    for x in rets[i + 1:i + 1 + h]:
        acc *= 1 + x
    return (acc - 1) * 100


def realized_vol(rets, i, h):
    """i일 다음날부터 h일 실현변동성(일간 표본표준편차 %)."""
    win = rets[i + 1:i + 1 + h]
    if len(win) < 2:
        return None
    return statistics.stdev(win) * 100


def main(path=None):
    path = path or os.path.join('data', FILENAME)
    if not os.path.exists(path):
        print(f'[국면채점] 채점표가 없습니다: {path}')
        print('           확정일이 한 번 지나야 첫 줄이 쌓입니다.')
        return 1

    rows = load(path)
    if len(rows) < 2:
        print(f'[국면채점] 아직 {len(rows)}일치입니다 — 채점은 쌓인 뒤에.')
        return 0

    dates = [r[0] for r in rows]
    levels = [r[1] for r in rows]
    rets = [r[2] for r in rows]
    print(f'채점표 {len(rows)}일 ({dates[0]} ~ {dates[-1]})')
    cnt = {lv: levels.count(lv) for lv in sorted(set(levels))}
    print('단계 분포: ' + ', '.join(f'{LABEL.get(k, k)}={v}' for k, v in cnt.items()))
    print()

    for h in HORIZONS:
        buckets = {}
        for i, lv in enumerate(levels):
            v = forward(rets, i, h)
            if v is not None:
                buckets.setdefault(lv, []).append(v)
        if not buckets:
            continue
        print(f'--- 판정 뒤 {h}거래일 수익률 ---')
        print(f"{'단계':10s} {'n':>4s} {'평균%':>8s} {'중앙%':>8s} {'양(+)':>6s}")
        for lv in sorted(buckets, key=lambda x: int(x)):
            v = buckets[lv]
            up = 100 * sum(1 for x in v if x > 0) / len(v)
            mark = '  ← 표본 부족' if len(v) < MIN_N else ''
            print(f'{LABEL.get(lv, lv):10s} {len(v):>4d} {sum(v)/len(v):+8.2f} '
                  f'{statistics.median(v):+8.2f} {up:5.0f}%{mark}')
        print()

    # 변동성 — 이 레포에서 유일하게 예측 가능하다고 확인된 축이다.
    buckets = {}
    for i, lv in enumerate(levels):
        v = realized_vol(rets, i, 10)
        if v is not None:
            buckets.setdefault(lv, []).append(v)
    if buckets:
        print('--- 판정 뒤 10거래일 실현변동성 ---')
        print(f"{'단계':10s} {'n':>4s} {'평균%':>8s} {'중앙%':>8s}")
        for lv in sorted(buckets, key=lambda x: int(x)):
            v = buckets[lv]
            mark = '  ← 표본 부족' if len(v) < MIN_N else ''
            print(f'{LABEL.get(lv, lv):10s} {len(v):>4d} {sum(v)/len(v):8.2f} '
                  f'{statistics.median(v):8.2f}{mark}')
        print()

    _monotonicity(levels, rets)
    return 0


def _monotonicity(levels, rets):
    """단계가 높을수록 이후 수익률이 높은가. 수익률은 아닐 것으로 예상된다."""
    means = []
    for lv in sorted(set(levels), key=lambda x: int(x)):
        v = [forward(rets, i, 5) for i, x in enumerate(levels) if x == lv]
        v = [x for x in v if x is not None]
        if v:
            means.append((lv, sum(v) / len(v), len(v)))
    if len(means) < 2:
        return
    mono = all(means[i][1] <= means[i + 1][1] for i in range(len(means) - 1))
    print('--- 단조성(5거래일) ---')
    print('  ' + ', '.join(f'{LABEL.get(a, a)}={b:+.2f}(n{c})' for a, b, c in means))
    print(f'  단조 증가: {mono}')
    if not mono:
        print('  → 예상된 결과다. 이 레포는 국면이 수익률을 예측하지 못함을 이미')
        print('     세 번 확인했다(11,988 / 5,085 / 450 검정). 국면은 상태 기술이다.')


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
