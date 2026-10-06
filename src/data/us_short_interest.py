"""FINRA 공매도 잔고(Equity Short Interest) — 키 없이 받는 공개 API.

거래소가 월 2회(15일·말일 결제 기준) 집계하고 FINRA가 7~8영업일 뒤 공표한다.
API에는 **공표된 것만** 있으므로 "가장 최근 결제일"을 받으면 그 자체로 시점 정보다.

2026-10-06 검증(S&P500 시점별 구성, 2018~2026)에서 종목 선택 신호 53개 중 다중검정을
통과한 유일한 신호가 이것이었다 — 잔고를 평균 거래량으로 나눈 '일수'가 낮은 상위 20%가
동일가중 대비 연 +5.7%p(t 3.8).
"""
from src.core import net

URL = 'https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest'
HEADERS = {'Content-Type': 'application/json', 'Accept': 'application/json'}
PAGE = 5000
# 결제일을 찾는 탐침 종목. 상장폐지될 일이 없는 것이면 된다.
_PROBE = 'AAPL'
_MAX_PAGES = 10


def _post(payload: dict) -> list:
    # required=True — 이 값이 없으면 회피 점수의 가장 강한 입력이 통째로 빈다.
    # 호출부가 잡아서 "이번 달은 점수를 새로 내지 않는다"로 처리한다.
    r = net.post(URL, policy=net.BULK, target='finra', headers=HEADERS, json=payload, required=True)
    body = r.json()
    if not isinstance(body, list):
        raise net.NetError(URL, 'unexpected_body')
    return body


def fetch_latest_settlement_date() -> str:
    rows = _post({'limit': PAGE, 'fields': ['settlementDate'],
                  'compareFilters': [{'compareType': 'EQUAL', 'fieldName': 'symbolCode',
                                      'fieldValue': _PROBE}]})
    dates = [r.get('settlementDate') for r in rows if r.get('settlementDate')]
    if not dates:
        raise net.NetError(URL, 'no_settlement_dates')
    return max(dates)


def fetch_short_interest(settlement_date: str) -> dict[str, float]:
    """그 결제일의 {심볼: 공매도 잔고 주식수}. 0주도 값이다(잔고 없음)."""
    out = {}
    for page in range(_MAX_PAGES):
        rows = _post({'limit': PAGE, 'offset': page * PAGE,
                      'fields': ['symbolCode', 'currentShortPositionQuantity'],
                      'compareFilters': [{'compareType': 'EQUAL', 'fieldName': 'settlementDate',
                                          'fieldValue': settlement_date}]})
        for r in rows:
            sym, qty = r.get('symbolCode'), r.get('currentShortPositionQuantity')
            if sym and qty is not None:
                out[str(sym).upper()] = float(qty)
        if len(rows) < PAGE:
            break
    return out


def fetch_latest_short_interest() -> tuple[str, dict[str, float]]:
    date = fetch_latest_settlement_date()
    return date, fetch_short_interest(date)
