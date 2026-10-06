"""SEC EDGAR companyfacts → 종목 선택용 재무 신호(US Sim4 회피 점수의 입력).

`us_fundamentals.py`(US Sim1용 EPS·매출 YoY)는 태그 하나씩 companyconcept를 부른다.
여기는 한 종목에 태그가 여덟 개쯤 필요해서 companyfacts 한 번으로 받는다.

**모든 신호는 `asof` 시점에 공시돼 있던 값만 쓴다**(`filed <= asof`). 운영에서는
asof=오늘이라 차이가 없지만, 같은 함수를 과거 시점에 돌려 연구 수치를 재현하려면
이 인자가 있어야 한다(2026-10-06 검증이 그렇게 했다).

전년 대비는 **같은 공시 안의 비교 열**을 쓴다. 10-Q·10-K는 당기와 전년 동기를
나란히 싣고, 주식 분할이 있으면 전년 값도 분할 후 기준으로 다시 적는다. 예전 공시의
값을 그대로 가져오면 분할한 회사가 "주식수 10배 증가"로 읽힌다.

값을 못 구하면 None이다 — 0으로 채우지 않는다(0은 "변화 없음"이라는 주장이다).
"""
import datetime as dt

from src.core import net

FACTS_URL = 'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'
# URL을 넣지 말 것 — SEC가 403을 준다(us_fundamentals.py와 같은 제약).
HEADERS = {'User-Agent': 'stockbot-research'}

REVENUE_TAGS = ('RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet',
                'RevenueFromContractWithCustomerIncludingAssessedTax', 'RevenuesNetOfInterestExpense')
TAGS = {
    'revenue': REVENUE_TAGS,
    'op_income': ('OperatingIncomeLoss',),
    'net_income': ('NetIncomeLoss',),
    'cfo': ('NetCashProvidedByUsedInOperatingActivities',),
    'assets': ('Assets',),
    'shares': ('WeightedAverageNumberOfDilutedSharesOutstanding',),
}
_UNITS = ('USD', 'shares')

_QUARTER = (75, 105)
_YEAR = (350, 380)
_YOY_TOLERANCE_DAYS = 25
# 가장 최근 공시가 이보다 오래됐으면 그 회사 신호는 쓰지 않는다. 분기 보고가
# 끊긴 회사(상폐 예정·외국계 전환)의 2년 전 숫자로 오늘 순위를 매기지 않기 위해서다.
MAX_FILING_AGE_DAYS = 200

SIGNALS = ('accr', 'issue', 'ag', 'd_opm', 'ni_chg')


def _date(s):
    return dt.date.fromisoformat(s) if isinstance(s, str) else s


def normalize(body: dict) -> dict:
    """companyfacts 응답 → {개념: [{'start','end','val','filed'}]}. 태그 우선순위 순으로 잇는다."""
    gaap = ((body or {}).get('facts') or {}).get('us-gaap') or {}
    out = {}
    for concept, tags in TAGS.items():
        rows = []
        for pri, tag in enumerate(tags):
            units = (gaap.get(tag) or {}).get('units') or {}
            for unit in _UNITS:
                for e in units.get(unit) or []:
                    try:
                        rows.append({'start': _date(e['start']) if e.get('start') else None,
                                     'end': _date(e['end']), 'val': float(e['val']),
                                     'filed': _date(e['filed']), 'pri': pri})
                    except (KeyError, TypeError, ValueError):
                        continue
        out[concept] = rows
    return out


def _days(row):
    return (row['end'] - row['start']).days


def _in(span, days):
    return span[0] <= days <= span[1]


def _latest_filed(rows, key):
    """같은 기간을 여러 번 공시했으면 가장 나중 것(정정·분할 재작성 반영)."""
    best = {}
    for r in rows:
        k = key(r)
        if k not in best or (r['filed'], -r['pri']) > (best[k]['filed'], -best[k]['pri']):
            best[k] = r
    return list(best.values())


def yoy_pair(rows, asof):
    """가장 최근 공시의 (당기, 전년 동기). 분기 열이 있으면 분기, 없으면(10-K) 연간.

    반환: {'cur','prior','end','kind','filed'} 또는 None."""
    known = [r for r in rows if r['start'] is not None and r['filed'] <= asof]
    if not known:
        return None
    filed = max(r['filed'] for r in known)
    if (asof - filed).days > MAX_FILING_AGE_DAYS:
        return None
    same = [r for r in known if r['filed'] == filed]
    for kind, span in (('q', _QUARTER), ('y', _YEAR)):
        cands = [r for r in same if _in(span, _days(r))]
        if not cands:
            continue
        cur = max(cands, key=lambda r: (r['end'], -r['pri']))
        target = cur['end'] - dt.timedelta(days=365)
        priors = [r for r in known if _in(span, _days(r))
                  and abs((r['end'] - target).days) <= _YOY_TOLERANCE_DAYS]
        if not priors:
            return None
        # 같은 공시에 실린 비교 열을 먼저 쓴다(분할 재작성이 반영된 값).
        prior = max(priors, key=lambda r: (r['filed'], -r['pri']))
        return {'cur': cur['val'], 'prior': prior['val'], 'end': cur['end'],
                'kind': kind, 'filed': filed}
    return None


def ttm(rows, asof):
    """최근 12개월 합. 현금흐름표는 연초 누적만 공시하므로
    `직전 회계연도 + 올해 누적 − 작년 같은 기간 누적`으로 만든다."""
    known = _latest_filed([r for r in rows if r['start'] is not None and r['filed'] <= asof],
                          lambda r: (r['start'], r['end']))
    if not known:
        return None
    end = max(r['end'] for r in known)
    at_end = [r for r in known if r['end'] == end]
    if (asof - max(r['filed'] for r in at_end)).days > MAX_FILING_AGE_DAYS:
        return None
    annual = [r for r in at_end if _in(_YEAR, _days(r))]
    if annual:
        return annual[0]['val']
    ytd = max(at_end, key=_days)            # 그 분기말에 끝나는 가장 긴 기간 = 연초 누적
    if _days(ytd) > _YEAR[0]:
        return None
    fy_end = ytd['start'] - dt.timedelta(days=1)
    prev_year = [r for r in known if _in(_YEAR, _days(r)) and abs((r['end'] - fy_end).days) <= 10]
    prev_ytd = [r for r in known
                if abs((r['start'] - (ytd['start'] - dt.timedelta(days=365))).days) <= 10
                and abs((r['end'] - (end - dt.timedelta(days=365))).days) <= _YOY_TOLERANCE_DAYS]
    if not prev_year or not prev_ytd:
        return None
    return prev_year[0]['val'] + ytd['val'] - prev_ytd[0]['val']


def instant_pair(rows, asof):
    """시점 값(자산)의 (최신, 1년 전)."""
    known = _latest_filed([r for r in rows if r['filed'] <= asof], lambda r: r['end'])
    if not known:
        return None
    cur = max(known, key=lambda r: r['end'])
    if (asof - cur['filed']).days > MAX_FILING_AGE_DAYS:
        return None
    target = cur['end'] - dt.timedelta(days=365)
    priors = [r for r in known if abs((r['end'] - target).days) <= _YOY_TOLERANCE_DAYS]
    prior = min(priors, key=lambda r: abs((r['end'] - target).days)) if priors else None
    return {'cur': cur['val'], 'prior': prior['val'] if prior else None}


def compute_signals(facts: dict, asof: dt.date) -> dict:
    """다섯 신호. 전부 **클수록 좋다**로 방향을 맞췄다(회피 점수가 그대로 평균 낸다).

    accr    −(순이익 − 영업현금흐름)/자산   이익이 현금으로 뒷받침되는가
    issue   −주식수 증가율                   주식을 찍어 내는가
    ag      −자산 증가율                     몸집을 급히 불리는가
    d_opm   영업이익률 전년 대비 변화
    ni_chg  순이익 증가분 / 전년 매출
    """
    out = dict.fromkeys(SIGNALS)
    rev = yoy_pair(facts.get('revenue') or [], asof)
    op = yoy_pair(facts.get('op_income') or [], asof)
    ni = yoy_pair(facts.get('net_income') or [], asof)
    sh = yoy_pair(facts.get('shares') or [], asof)
    assets = instant_pair(facts.get('assets') or [], asof)

    def aligned(a, b):
        return a and b and a['kind'] == b['kind'] and a['end'] == b['end']

    if assets and assets['cur'] > 0:
        ni_ttm = ttm(facts.get('net_income') or [], asof)
        cfo_ttm = ttm(facts.get('cfo') or [], asof)
        if ni_ttm is not None and cfo_ttm is not None:
            out['accr'] = -(ni_ttm - cfo_ttm) / assets['cur']
        if assets['prior'] and assets['prior'] > 0:
            out['ag'] = -(assets['cur'] / assets['prior'] - 1)
    if sh and sh['cur'] > 0 and sh['prior'] > 0:
        out['issue'] = -(sh['cur'] / sh['prior'] - 1)
    if aligned(rev, op) and rev['cur'] > 0 and rev['prior'] > 0:
        out['d_opm'] = op['cur'] / rev['cur'] - op['prior'] / rev['prior']
    if aligned(rev, ni) and rev['prior'] > 0:
        out['ni_chg'] = (ni['cur'] - ni['prior']) / rev['prior']
    return out


def fetch_company_facts(cik: str) -> dict | None:
    """정규화한 facts. 못 받으면 None(이유는 로그에 남긴다)."""
    reasons = {}
    r = net.get(FACTS_URL.format(cik=cik), policy=net.BULK, target='sec',
                headers=HEADERS, reasons=reasons)
    if r is None:
        print(f'[us_factors] companyfacts 조회 실패 (CIK {cik}): {", ".join(reasons) or "unknown"}')
        return None
    try:
        return normalize(r.json())
    except ValueError as e:
        print(f'[us_factors] companyfacts 파싱 실패 (CIK {cik}): {e}')
        return None
