"""패닉 바닥 판정에 쓰는 거시 지표 수집·계산.

지표는 2026-10-07 탐색에서 살아남은 것만 쓴다. 선정 근거는
`docs/research/2026-10-07-panic-floor.md`.

- 미국 경제정책 불확실성 EPU (`USEPUINDXD`, 일별 1985~)
- 세인트루이스 금융스트레스 (`STLFSI4`, 주별 1993~)
- 표시 전용 보조: 유가 WTI, 원달러, 수익률곡선 10Y−2Y

FRED는 API 키 없이 `fredgraph.csv?id=...` 로 전체 이력을 준다(2026-10-06 실측,
18계열 전부 200). 실패하면 값을 지어내지 않고 사유와 함께 None을 돌려준다.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime

from src.core import net

FRED_CSV = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}'

# 판정에 쓰는 두 계열. 보조 계열은 표시 전용이라 실패해도 판정을 막지 않는다.
EPU_ID = 'USEPUINDXD'
STRESS_ID = 'STLFSI4'
AUX_IDS = {'유가WTI': 'DCOILWTICO', '원달러': 'DEXKOUS', '수익률곡선10_2': 'T10Y2Y'}

# 롤링 창. 2026-10-07 탐색과 같은 값이다 — 바꾸면 그 표가 이 코드를 설명하지 않는다.
Z_WINDOW = 60      # 3개월 변화의 z를 내는 롤링 개월 수
Z_MIN = 30         # 창이 이만큼은 차야 z를 낸다
PCT_MIN = 60       # 백분위를 내는 데 필요한 최소 관측 수


def fetch_fred_monthly(series_id, *, reasons=None):
    """FRED 한 계열 → {'YYYY-MM': 월평균}. 실패하면 (None, 사유)."""
    res = net.get(FRED_CSV.format(sid=series_id), policy=net.BULK,
                  target='fred', reasons=reasons)
    if res is None:
        return None, f'{series_id} fetch failed'
    try:
        rows = list(csv.reader(io.StringIO(res.text)))
    except Exception as e:
        return None, f'{series_id} parse {type(e).__name__}'
    if len(rows) < 3:
        return None, f'{series_id} rows<3 ({len(rows)})'

    buckets: dict[str, list[float]] = {}
    for r in rows[1:]:
        if len(r) < 2:
            continue
        d, v = r[0].strip(), r[1].strip()
        if len(d) < 7:
            continue
        try:
            x = float(v)
        except ValueError:
            continue       # FRED는 결측을 '.'로 준다 — 0으로 채우지 않는다
        buckets.setdefault(d[:7], []).append(x)
    if len(buckets) < PCT_MIN:
        return None, f'{series_id} months<{PCT_MIN} ({len(buckets)})'
    monthly = {k: sum(v) / len(v) for k, v in sorted(buckets.items())}
    counts = {k: len(v) for k, v in buckets.items()}
    return (monthly, counts), None


def _series_tail(monthly, n):
    """최근 n개월 값 리스트(오래된 것 → 최신)."""
    keys = sorted(monthly)
    return [monthly[k] for k in keys[-n:]]


def _stdev(xs):
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return var ** 0.5


def change_z(monthly, lag=3, window=Z_WINDOW):
    """lag개월 변화의 롤링 z. 못 내면 (None, 사유)."""
    keys = sorted(monthly)
    if len(keys) < lag + Z_MIN + 1:
        return None, f'months<{lag + Z_MIN + 1} ({len(keys)})'
    ch = [monthly[keys[i]] - monthly[keys[i - lag]] for i in range(lag, len(keys))]
    base = ch[-window:] if len(ch) >= window else ch
    if len(base) < Z_MIN:
        return None, f'z window<{Z_MIN} ({len(base)})'
    sd = _stdev(base)
    if sd is None or sd < 1e-9:
        return None, 'z stdev=0'
    return (ch[-1] - sum(base) / len(base)) / sd, None


def change_percentile(monthly, lag=12):
    """lag개월 변화의 전체 이력 대비 백분위(0~100). 못 내면 (None, 사유)."""
    keys = sorted(monthly)
    if len(keys) < lag + PCT_MIN:
        return None, f'months<{lag + PCT_MIN} ({len(keys)})'
    ch = [monthly[keys[i]] - monthly[keys[i - lag]] for i in range(lag, len(keys))]
    cur = ch[-1]
    return 100.0 * sum(1 for x in ch if x < cur) / len(ch), None


def yoy_pct(monthly, lag=12):
    keys = sorted(monthly)
    if len(keys) < lag + 1:
        return None
    prev = monthly[keys[-1 - lag]]
    if not prev:
        return None
    return (monthly[keys[-1]] / prev - 1) * 100


def collect(*, log=print, reasons=None):
    """판정에 필요한 지표를 모은다.

    반환: (metrics, errors). metrics['ready']가 False면 판정하지 않는다 —
    없는 값을 0으로 채우고 '정상'이라고 말하는 것이 제일 위험하다.
    """
    errors = []
    m: dict = {'asof': datetime.utcnow().strftime('%Y-%m-%d'), 'ready': False}

    got, err = fetch_fred_monthly(EPU_ID, reasons=reasons)
    epu, epu_n = got if got else (None, None)
    if err:
        errors.append(err)
    got2, err2 = fetch_fred_monthly(STRESS_ID, reasons=reasons)
    stress, stress_n = got2 if got2 else (None, None)
    if err2:
        errors.append(err2)

    if epu:
        keys = sorted(epu)
        m['epu_month'] = keys[-1]
        m['epu_level'] = round(epu[keys[-1]], 2)
        # 이번 달이 미완결이면 표본이 적다 — 7일치 평균을 한 달처럼 쓰면 흔들린다
        m['epu_obs'] = epu_n.get(keys[-1]) if epu_n else None
        typical = sorted(epu_n.values())[len(epu_n) // 2] if epu_n else None
        m['epu_month_partial'] = bool(typical and m['epu_obs'] and
                                      m['epu_obs'] < typical * 0.6)
        pct, e = change_percentile(epu, 12)
        if e:
            errors.append(f'epu pct: {e}')
        else:
            m['epu_12m_pct'] = round(pct, 1)
        z, e = change_z(epu, 3)
        if e:
            errors.append(f'epu z: {e}')
        else:
            m['epu_z'] = round(z, 2)
    if stress:
        keys = sorted(stress)
        m['stress_month'] = keys[-1]
        m['stress_level'] = round(stress[keys[-1]], 2)
        m['stress_obs'] = stress_n.get(keys[-1]) if stress_n else None
        z, e = change_z(stress, 3)
        if e:
            errors.append(f'stress z: {e}')
        else:
            m['stress_z'] = round(z, 2)

    for label, sid in AUX_IDS.items():
        got3, e = fetch_fred_monthly(sid, reasons=reasons)
        if e or not got3:
            errors.append(f'aux {label}: {e}')
            continue
        s = got3[0]
        keys = sorted(s)
        if label == '수익률곡선10_2':
            m['aux_곡선10_2'] = round(s[keys[-1]], 2)
        else:
            v = yoy_pct(s)
            if v is not None:
                m[f'aux_{label}_yoy'] = round(v, 1)

    m['ready'] = all(k in m for k in ('epu_12m_pct', 'epu_z', 'stress_z'))
    if not m['ready']:
        log(f"[PanicFloor] 지표 미완성 — 판정 보류: {'; '.join(errors) or 'unknown'}")
    m['errors'] = errors
    return m, errors


def get_metrics(prev=None, *, today=None, log=print, reasons=None):
    """하루 한 번만 받는다.

    prev: 직전 런의 metrics(심 state에 실려 db-data로 왕복한다). 별도 캐시 파일을
      두지 않는 이유는 동기화 목록이 매니페스트에서 파생되기 때문이다 — 목록에
      없는 파일은 복원되지 않고, 그러면 FRED가 죽은 날 폴백이 영영 동작하지 않는다.
    """
    today = today or datetime.utcnow().strftime('%Y-%m-%d')
    if prev and prev.get('asof') == today and prev.get('ready'):
        return prev
    m, _ = collect(log=log, reasons=reasons)
    if m.get('ready'):
        return m
    # 새로 받은 게 불완전하면 직전 값이라도 쓴다 — 단 그 사실을 표시한다.
    if prev and prev.get('ready'):
        stale = dict(prev)
        stale['stale'] = True
        stale['stale_reason'] = '; '.join(m.get('errors') or ['unknown'])
        return stale
    return m
