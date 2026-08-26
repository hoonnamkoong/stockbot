"""SEC EDGAR XBRL — EPS·매출 YoY 성장률(SEPA 실적 가속 필터용).

키 불필요, 완전 무료. SEC 정책상 User-Agent로 신원을 밝혀야 한다 — 다만 UA에
URL이 들어가면 403으로 막힌다(2026-08-26 실측: www.sec.gov·data.sec.gov 양쪽).
URL 없는 이름만으로 통과한다.

EDGAR의 분기 facts에는 같은 종료일(end)에 대해 "이번 분기"와 "연초부터 누적"
값이 섞여 나온다 — 둘 다 같은 태그를 쓴다. 진짜 분기 값만 골라내려면 duration
(end - start)이 순수 1개 분기 길이(약 80~100일)인 항목만 남겨야 한다. 이 필터
없이 최신값만 집으면 절반의 확률로 연간 누적치를 "이번 분기 EPS"로 잘못 읽는다.
"""
import datetime as dt

import requests

TICKERS_URL = 'https://www.sec.gov/files/company_tickers.json'
CONCEPT_URL = 'https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json'
# URL을 넣지 말 것 — SEC가 403을 준다. tests/test_us_fundamentals.py가 이걸 지킨다.
HEADERS = {'User-Agent': 'stockbot-research'}

REVENUE_TAGS = [
    'Revenues',
    'RevenueFromContractWithCustomerExcludingAssessedTax',
    'SalesRevenueNet',
]

_MIN_QUARTER_DAYS = 80
_MAX_QUARTER_DAYS = 100


def fetch_cik_map() -> dict[str, str]:
    """ticker(대문자) → 10자리 zero-padded CIK."""
    r = requests.get(TICKERS_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    body = r.json()
    out = {}
    for entry in body.values():
        ticker = str(entry.get('ticker', '')).upper()
        cik = entry.get('cik_str')
        if ticker and cik is not None:
            out[ticker] = str(cik).zfill(10)
    return out


def _quarterly_entries(units: dict) -> list[dict]:
    """분기 길이(80~100일)인 항목만. 연간 누적·반기 누적을 제외한다."""
    entries = units.get('USD/shares') or units.get('USD') or []
    out = []
    for e in entries:
        try:
            start = dt.date.fromisoformat(e['start'])
            end = dt.date.fromisoformat(e['end'])
        except (KeyError, ValueError):
            continue
        days = (end - start).days
        if _MIN_QUARTER_DAYS <= days <= _MAX_QUARTER_DAYS:
            out.append({'end': end, 'val': e.get('val')})
    return sorted(out, key=lambda x: x['end'])


def _latest_yoy(entries: list[dict]) -> float | None:
    """가장 최근 분기 값과, 그로부터 약 1년 전(345~385일) 분기 값의 YoY."""
    if not entries:
        return None
    latest = entries[-1]
    target_start = latest['end'] - dt.timedelta(days=385)
    target_end = latest['end'] - dt.timedelta(days=345)
    prior = next((e for e in entries if target_start <= e['end'] <= target_end), None)
    if prior is None or not prior['val']:
        return None
    return (latest['val'] - prior['val']) / abs(prior['val']) * 100.0


def _fetch_concept(cik: str, tag: str) -> dict | None:
    url = CONCEPT_URL.format(cik=cik, tag=tag)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        # 조용히 None을 돌려주면 SEC가 UA를 막았을 때 워치리스트가 이유 없이 빈다.
        print(f'[us_fundamentals] {tag} 조회 실패 (CIK {cik}): {e}')
        return None


def fetch_eps_revenue_growth(cik: str) -> dict:
    """EPS·매출 YoY(%). 태그를 못 찾거나 전년동기 짝이 없으면 None(측정 불가)."""
    eps_growth = None
    eps_body = _fetch_concept(cik, 'EarningsPerShareDiluted')
    if eps_body:
        eps_growth = _latest_yoy(_quarterly_entries(eps_body.get('units') or {}))

    revenue_growth = None
    for tag in REVENUE_TAGS:
        body = _fetch_concept(cik, tag)
        if not body:
            continue
        revenue_growth = _latest_yoy(_quarterly_entries(body.get('units') or {}))
        if revenue_growth is not None:
            break

    return {'eps_growth_yoy': eps_growth, 'revenue_growth_yoy': revenue_growth}
