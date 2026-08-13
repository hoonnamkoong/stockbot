"""KIS 기간별매매손익(TTTC8715R) — **확정** 실현손익.

원장의 `realized_pnl`은 주문가 추정치로 쌓은 값이다. 매도 주문을 낼 때
`accrue_realized_pnl`이 추정치를 더하고, 체결 조회가 되면 `_correct_sell`이
실측으로 갈아끼운다. 그런데 체결 조회가 끝내 안 되면 그 추정치가 원장에
영구히 굳고, 그 값은 표시용이 아니라 `effective_budget = budget + realized_pnl`
로 **실주문 사이징에 직접 들어간다** — 지어낸 숫자가 예산이 된다.

대시보드(src/lib/kis-api.ts)는 이미 이 API를 쓰고 있었다. 다만 원장 값과
나란히 **보여주기만** 했고, 사이징을 계산하는 Python은 그 값을 못 봤다.
필드명(pdno·trad_dt·sll_qty·rlzt_pfls)은 그 경로에서 실호출로 확정된 것이다.

**조회 실패와 '매도가 없었다'를 반드시 구분한다.** 호출부가 정반대로 처리한다:
실패면 원장을 손대지 않고(모르는 채로 지우지 않는다), 없었으면 추정치를
통째로 되돌린다(그 매도는 체결되지 않았다).
"""
import os
import requests
from datetime import datetime, timedelta

from src.trade.auth import get_access_token, get_base_url

_TIMEOUT_SEC = 10


def _kis_date(value: str) -> str:
    """'2026-08-12' / '2026-08-12T15:29:21' / '20260812' → '20260812'."""
    return (value or '')[:10].replace('-', '')


def _request_period_profit(from_date: str, to_date: str,
                           code: str = '') -> list[dict] | None:
    """원본 조회. **실패는 None, 성공은 리스트(0건 포함).**

    이 구분이 이 모듈의 존재 이유다 — `executions._request_executions`와 같다.
    """
    token = get_access_token()
    if not token:
        return None

    app_key = os.environ.get("KIS_APP_KEY", "").strip().replace("\n", "")
    app_secret = os.environ.get("KIS_APP_SECRET", "").strip().replace("\n", "")
    account_no_full = os.environ.get("KIS_ACCOUNT_NO", "").strip().replace("\n", "")
    if not account_no_full:
        return None

    clean_acc = account_no_full.replace('-', '').replace(' ', '')
    if len(clean_acc) < 10:
        return None

    # 모의투자는 이 TR을 지원하지 않는다. 실패로 떨어뜨린다 — 0건으로 읽으면
    # '매도가 없었다'가 되어 호출부가 추정치를 되돌린다(없는 사실을 만든다).
    if os.environ.get("KIS_IS_VIRTUAL", "false").lower() == "true":
        return None

    try:
        res = requests.get(
            f"{get_base_url()}/uapi/domestic-stock/v1/trading/inquire-period-trade-profit",
            headers={
                "content-type": "application/json; charset=utf-8",
                "authorization": f"Bearer {token}",
                "appkey": app_key,
                "appsecret": app_secret,
                "tr_id": "TTTC8715R",
                "custtype": "P",
            },
            params={
                "CANO": clean_acc[:8],
                "ACNT_PRDT_CD": clean_acc[8:10],
                "SORT_DVSN": "00",
                "PDNO": code or "",
                "INQR_STRT_DT": from_date,
                "INQR_END_DT": to_date,
                "CBLC_DVSN": "00",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
            timeout=_TIMEOUT_SEC,
        )
    except Exception:
        return None

    if res.status_code != 200:
        return None
    try:
        data = res.json()
    except Exception:
        return None
    if data.get('rt_cd') != '0':
        return None
    rows = data.get('output1')
    return rows if isinstance(rows, list) else None


def lookup_realized_pnl(code: str, date: str, request=None):
    """그 종목이 그 날 확정한 실현손익.

    반환 `(ok, result)`:
      - `(False, None)` — 조회 실패. **모른다.** 원장을 손대면 안 된다.
      - `(True, None)`  — 조회는 됐고 그 날 그 종목의 매도가 없다(미체결).
      - `(True, {'qty': 매도수량, 'amount': 실현손익원})` — 확정값.

    같은 날 같은 종목이 여러 행으로 쪼개져 올 수 있다(분할 체결). 합산한다.

    수량·손익 필드가 비면 그 행은 버린다 — 필드 부재를 0으로 읽으면 '손익 0'
    이라는 거짓이 된다. 모든 행이 그렇게 버려지면 `(True, None)`이 아니라
    `(False, None)`이다: 매도 행은 있었는데 값을 못 읽은 것이므로 '매도 없음'과
    다르다.
    """
    d = _kis_date(date)
    if not code or len(d) != 8:
        return False, None

    rows = (request or _request_period_profit)(d, d, code)
    if rows is None:
        return False, None

    mine = [r for r in rows if str(r.get('pdno') or '') == code
            and _kis_date(str(r.get('trad_dt') or '')) == d]
    if not mine:
        return True, None

    qty = 0
    amount = 0.0
    read = 0
    for r in mine:
        if r.get('rlzt_pfls') in (None, '') or r.get('sll_qty') in (None, ''):
            continue
        try:
            q = int(float(r['sll_qty']))
            a = float(r['rlzt_pfls'])
        except (TypeError, ValueError):
            continue
        if q <= 0:
            continue
        qty += q
        amount += a
        read += 1

    if not read:
        return False, None
    return True, {'qty': qty, 'amount': amount}
