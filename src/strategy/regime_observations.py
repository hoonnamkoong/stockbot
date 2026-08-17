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
import glob
import io
import os
from decimal import ROUND_HALF_UP, Decimal

OBS_HEADER = [
    'ts_kst', 'breadth', 'momentum', 'trend', 'sample', 'source',
    # 아래 8열은 2026-08 추가. 전부 기존 네이버 응답에서 파생한다(추가 요청 0건).
    # 없으면 빈 칸이다 — 0으로 채우면 '측정 못 함'과 '진짜 0'이 합쳐진다.
    'breadth_cap',                      # 시총가중 상승비율. 동일가중 breadth와 갈리는 날이 전환일이다
    'p10', 'p25', 'p75', 'p90',         # 등락률 분위수. p50은 momentum과 같아 넣지 않는다
    'up', 'down',                       # 상승·하락 종목 수. flat = sample - up - down
    'turnover',                         # Σ(현재가 × 거래량) / 1e8, 억원. 정확한 거래대금이 아닌 근사다
]

OBS_EXTRA = tuple(OBS_HEADER[6:])

# CSV 열 이름 → 레코드 키. ts_kst만 다르다(기존 계약 유지).
_RECORD_KEY = {'ts_kst': 'ts'}

# 열별 소수 자릿수.
_DECIMALS = {'breadth': 1, 'momentum': 2, 'trend': 1, 'breadth_cap': 1,
             'p10': 2, 'p25': 2, 'p75': 2, 'p90': 2}
_INT_COLS = ('sample', 'up', 'down', 'turnover')
_TEXT_COLS = ('ts_kst', 'source')

# 계산 창의 기본 거래일 수. **저장 창이 아니다** — 2026-08까지는 append가 매번
# 이걸로 잘라서, 기다려도 표본이 60거래일에서 늘지 않았다. 지금은 판정기·라벨러가
# 분위수 창을 잡을 때만 쓴다.
MAX_DISTINCT_DATES = 60

# 읽기 전용 아카이브. 2026-08 월별 분할 이전에 쌓인 426행이 여기 있다.
# 새 쓰기는 전부 month_path()로 간다.
OBS_ARCHIVE = 'regime_observations.csv'

_MONTH_GLOB = 'regime_observations_[0-9][0-9][0-9][0-9]-[0-9][0-9].csv'


def month_path(now, data_dir: str = 'data') -> str:
    """월별 분할. rank_snapshot·sim_diag·post_archive와 같은 규약이다.

    한 파일이 무한정 커지는 것을 막는다. append가 매번 전체 재작성이고
    db-data가 10분마다 커밋을 받으므로, 단일 파일이면 1년차에 커밋당
    ~810KB짜리 blob이 하루 39개씩 쌓인다.
    """
    return os.path.join(data_dir, f"regime_observations_{now.strftime('%Y-%m')}.csv")


def load_all_observations(data_dir: str = 'data') -> list:
    """아카이브 + 월별 전부를 시각 오름차순 단일 리스트로.

    같은 `ts`가 두 파일에 있으면 **먼저 읽은 것**(아카이브 우선)을 남긴다.
    이행 구간에 아카이브와 그 달 파일이 같은 분을 담을 수 있는데, 두 번 세면
    표본이 부풀고 값이 다르면 같은 시각에 정답이 둘이 된다.
    """
    paths = [os.path.join(data_dir, OBS_ARCHIVE)]
    paths += sorted(glob.glob(os.path.join(data_dir, _MONTH_GLOB)))

    seen, rows = set(), []
    for p in paths:
        if not os.path.exists(p):
            continue
        with io.open(p, encoding='utf-8-sig') as f:
            for r in parse_observations(f.read()):
                if r['ts'] in seen:
                    continue
                seen.add(r['ts'])
                rows.append(r)
    rows.sort(key=lambda r: r['ts'])
    return rows


def _round_str(value, ndigits):
    """반올림 결과를 문자열로. 0.5 지점은 항상 위(절대값 큰 쪽)로 — 파이썬 기본
    포맷(f'{x:.2f}')은 은행가 반올림이라 -0.125가 -0.12로 잘려 표본값과 어긋난다."""
    quantum = Decimal('1').scaleb(-ndigits)
    return str(Decimal(str(float(value))).quantize(quantum, rounding=ROUND_HALF_UP))


def format_row(rec):
    """레코드 dict → CSV 한 행(문자열 리스트).

    없는 값은 **빈 칸**이다. 0으로 적으면 '측정 못 함'과 '진짜 0'이 한 값이 되고,
    그건 나중에 어떤 방법으로도 되돌릴 수 없다.
    """
    out = []
    for col in OBS_HEADER:
        v = rec.get(_RECORD_KEY.get(col, col))
        if col in _TEXT_COLS:
            out.append('' if v is None else str(v))
        elif v is None:
            out.append('')
        elif col in _INT_COLS:
            out.append(str(int(v)))
        else:
            out.append(_round_str(v, _DECIMALS[col]))
    return out


def _opt(value, cast):
    """빈 칸·부재·파싱 실패는 전부 None. 있는 값만 캐스팅한다."""
    if value is None or value == '':
        return None
    try:
        return cast(value)
    except ValueError:
        return None


def parse_observations(text):
    """CSV 텍스트 → 관측 리스트. 깨진 행은 건너뛰고 나머지를 살린다.

    **구 스키마(6열) 파일도 읽는다.** db-data의 아카이브가 그 모양이고,
    못 읽으면 426행이 통째로 사라진다. 없는 열은 None이다.
    """
    rows = []
    reader = csv.reader(io.StringIO(text.lstrip('﻿')))
    header = None
    for values in reader:
        if not values:
            continue
        if header is None:
            header = [c.strip() for c in values]
            continue
        # 파일 자신의 헤더 길이로 잰다. len(OBS_HEADER)로 재면 6열 아카이브가 통째로 버려진다.
        if len(values) < len(header):
            continue
        rec = dict(zip(header, [v.strip() for v in values]))
        try:
            row = {
                'ts': rec['ts_kst'],
                'breadth': float(rec['breadth']),
                'momentum': float(rec['momentum']),
                'trend': _opt(rec.get('trend'), float),
                'sample': int(rec['sample']),
                'source': rec['source'],
            }
        except (KeyError, ValueError):
            continue
        for col in OBS_EXTRA:
            row[col] = _opt(rec.get(col), int if col in _INT_COLS else float)
        rows.append(row)
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


def append_observation(path, ts, breadth, momentum, trend, sample, source, extra=None):
    """관측 한 건 append. 같은 분이 이미 있으면 아무것도 하지 않고 False.

    같은 분의 재실행이 값을 흔들면 이력이 런 재시도 여부에 의존하게 된다 —
    첫 값을 유지한다.

    `extra`는 OBS_EXTRA의 부분집합이다. 모르는 키는 **예외**다 — 조용히 버리면
    오타 하나로 그 기간의 열이 통째로 비고, 몇 달 뒤에나 발견된다.
    """
    extra = dict(extra or {})
    unknown = set(extra) - set(OBS_EXTRA)
    if unknown:
        raise ValueError(f"알 수 없는 관측 열: {sorted(unknown)}")

    existing = []
    if os.path.exists(path):
        with io.open(path, encoding='utf-8-sig') as f:
            existing = parse_observations(f.read())
        if any(r['ts'] == str(ts) for r in existing):
            return False

    row = {'ts': str(ts), 'breadth': float(breadth), 'momentum': float(momentum),
           'trend': trend, 'sample': int(sample), 'source': str(source)}
    row.update({col: extra.get(col) for col in OBS_EXTRA})
    existing.append(row)

    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(OBS_HEADER)
        for r in existing:
            w.writerow(format_row(r))
    os.replace(tmp, path)   # 중간에 죽어도 이력이 반토막 나지 않는다
    return True
