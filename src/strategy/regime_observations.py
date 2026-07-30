# -*- coding: utf-8 -*-
"""국면 관측 이력 — 10분 해상도로 (폭, 강도)를 쌓는다.

**왜 이 파일이 생겼나.** 리베로는 10분마다 도는데 `_hour_label`이 시각을 'HH:00'으로
깎아 같은 시간대의 첫 관측만 남겼다. 관측의 5/6이 버려졌고, `intraday` 버킷은 날짜가
바뀌면 리셋되며 백필은 KIS **당일**분봉이라 과거 재구성도 불가능했다. 그래서 10분 지평
모델을 학습·검증할 이력이 0이었다.

**위치**: `data/regime_observations.csv`. 워크플로 수정이 필요 없다 — scraper.yml이 런
시작에 `git checkout db-data -- data/`로 복원하고 끝에 `data/*.csv`를 db-data로 복사한다.
그래서 append가 런 사이에 이어진다.

**표본이 적어도 버리지 않는다.** `_fetch_top100_breadth`는 표본 80 미만이면 None을
반환해 관측을 통째로 폐기하는데, 확률 모형에서 적은 표본은 폐기 대상이 아니라
**약한 증거**다(regime_filter가 sigma를 표본수로 보정한다).
"""
import csv
import io
import os
from decimal import ROUND_HALF_UP, Decimal

OBS_HEADER = ['ts_kst', 'breadth', 'momentum', 'trend', 'sample', 'source']

# 롤링 보관 거래일. 60일 × 39슬롯 ≈ 2,340행. 행 수 상한이 아니라 거래일 수로 자르는
# 이유: 런이 지연되거나 건너뛴 날이 있어도 보관 기간의 뜻이 변하지 않는다.
MAX_DISTINCT_DATES = 60

# 파이프라인이 쓰는 상대 경로. `data/` 아래 `.csv`라는 것이 계약이다 —
# scraper.yml이 런 시작에 db-data에서 data/를 복원하고 끝에 data/*.csv를 배포한다.
# 이 두 조건 중 하나만 어긋나도 이력이 런 사이에 이어지지 않는다.
OBS_PATH_REL = 'data/regime_observations.csv'


def _round_str(value, ndigits):
    """반올림 결과를 문자열로. 0.5 지점은 항상 위(절대값 큰 쪽)로 — 파이썬 기본
    포맷(f'{x:.2f}')은 은행가 반올림이라 -0.125가 -0.12로 잘려 표본값과 어긋난다."""
    quantum = Decimal('1').scaleb(-ndigits)
    return str(Decimal(str(float(value))).quantize(quantum, rounding=ROUND_HALF_UP))


def format_row(ts, breadth, momentum, trend, sample, source):
    """CSV 한 행. trend는 없을 수 있다(일봉 CSV 파싱 실패) → 빈 칸으로 남긴다."""
    return [
        str(ts),
        _round_str(breadth, 1),
        _round_str(momentum, 2),
        '' if trend is None else _round_str(trend, 1),
        str(int(sample)),
        str(source),
    ]


def parse_observations(text):
    """CSV 텍스트 → 관측 리스트. 깨진 행은 건너뛰고 나머지를 살린다."""
    rows = []
    reader = csv.reader(io.StringIO(text.lstrip('﻿')))
    header = None
    for values in reader:
        if not values:
            continue
        if header is None:
            header = [c.strip() for c in values]
            continue
        if len(values) < len(OBS_HEADER):
            continue
        rec = dict(zip(header, [v.strip() for v in values]))
        try:
            rows.append({
                'ts': rec['ts_kst'],
                'breadth': float(rec['breadth']),
                'momentum': float(rec['momentum']),
                'trend': None if rec['trend'] == '' else float(rec['trend']),
                'sample': int(rec['sample']),
                'source': rec['source'],
            })
        except (KeyError, ValueError):
            continue
    return rows


def trim_to_recent_dates(rows, max_dates=MAX_DISTINCT_DATES):
    """최근 `max_dates`개 거래일의 행만 남긴다(순서 유지)."""
    dates = []
    for r in rows:
        d = r['ts'][:10]
        if d not in dates:
            dates.append(d)
    keep = set(dates[-max_dates:])
    return [r for r in rows if r['ts'][:10] in keep]


def append_observation(path, ts, breadth, momentum, trend, sample, source):
    """관측 한 건 append. 같은 분이 이미 있으면 아무것도 하지 않고 False.

    같은 분의 재실행이 값을 흔들면 이력이 런 재시도 여부에 의존하게 된다 —
    첫 값을 유지한다(measurements의 기존 동작과 같은 규칙).
    """
    existing = []
    if os.path.exists(path):
        with io.open(path, encoding='utf-8-sig') as f:
            existing = parse_observations(f.read())
        if any(r['ts'] == str(ts) for r in existing):
            return False

    existing.append({'ts': str(ts), 'breadth': float(breadth), 'momentum': float(momentum),
                     'trend': trend, 'sample': int(sample), 'source': str(source)})
    kept = trim_to_recent_dates(existing)

    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(OBS_HEADER)
        for r in kept:
            w.writerow(format_row(r['ts'], r['breadth'], r['momentum'],
                                  r['trend'], r['sample'], r['source']))
    os.replace(tmp, path)   # 중간에 죽어도 이력이 반토막 나지 않는다
    return True
