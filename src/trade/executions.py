"""KIS 일별체결조회(TTTC8001R) — 실제 체결가·체결수량 실측.

E10(2026-08-04 스크래퍼 지연 재설계): 프로그램 원장의 avg_price는 지금까지
주문가 추정치였다(program_trader.py의 기존 주석이 인정한다). 이 모듈은 그
추정치를 실제 체결과 대조할 수 있는 실측 소스를 제공한다.

이번 배포는 조회·기록까지만 한다(설계 문서 Rollback Plan) — 원장 값을 자동으로
덮어쓰는 로직은 아직 없다. 추정치와 실측의 차이를 며칠 관찰한 뒤 다음 단계에서
붙인다.
"""
import os
import requests
from datetime import datetime, timedelta

from src.trade.auth import get_access_token, get_base_url


FILLED = 'filled'
UNFILLED = 'unfilled'
UNKNOWN = 'unknown'


def _side(code: str) -> str:
    return 'SELL' if code == '01' else 'BUY'


def _request_executions(from_date: str | None = None, to_date: str | None = None,
                         odno: str = '') -> list[dict] | None:
    """KIS 일별체결조회 원본. **조회 실패는 None, 성공은 리스트(0건 포함).**

    이 구분이 이 함수의 존재 이유다. 호출부가 미체결('조회는 됐는데 없다')과
    조회 실패('모른다')를 반대로 처리하기 때문이다.
    """
    token = get_access_token()
    if not token:
        return None

    app_key = os.environ.get("KIS_APP_KEY", "").strip().replace("\n", "")
    app_secret = os.environ.get("KIS_APP_SECRET", "").strip().replace("\n", "")
    account_no_full = os.environ.get("KIS_ACCOUNT_NO", "").strip().replace("\n", "")
    is_virtual = os.environ.get("KIS_IS_VIRTUAL", "false").lower() == "true"
    if not account_no_full:
        return None

    clean_acc = account_no_full.replace('-', '').replace(' ', '')
    if len(clean_acc) < 10:
        return None
    cano = clean_acc[:8]
    acnt_prdt_cd = clean_acc[8:10]

    base_url = get_base_url()
    tr_id = 'VTTC8001R' if is_virtual else 'TTTC8001R'

    now_kst = datetime.utcnow() + timedelta(hours=9)
    to_date = to_date or now_kst.strftime('%Y%m%d')
    from_date = from_date or to_date

    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P",
    }
    params = {
        "CANO": cano, "ACNT_PRDT_CD": acnt_prdt_cd,
        "INQR_STRT_DT": from_date, "INQR_END_DT": to_date,
        "SLL_BUY_DVSN_CD": "00",  # 00: 전체
        "INQR_DVSN": "00",        # 00: 역순(최신→과거)
        "PDNO": "", "CCLD_DVSN": "01",  # 01: 체결만
        "ORD_GNO_BRNO": "", "ODNO": odno,
        "INQR_DVSN_3": "00", "INQR_DVSN_1": "",
        "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
    }

    try:
        res = requests.get(
            f"{base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
            headers=headers, params=params, timeout=10,
        )
        if res.status_code != 200:
            return None
        data = res.json()
        if data.get('rt_cd') != '0':
            return None
    except Exception:
        return None

    rows = data.get('output1') or []
    fills = []
    for item in rows:
        try:
            price = float(item.get('avg_prvs') or item.get('ccld_avg_unpr') or 0)
            qty = int(item.get('tot_ccld_qty') or 0)
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        fills.append({
            'odno': item.get('odno', ''),
            'code': item.get('pdno', ''),
            'name': item.get('prdt_name', ''),
            'side': _side(item.get('sll_buy_dvsn_cd', '')),
            'price': price,
            'qty': qty,
            'amount': float(item.get('tot_ccld_amt') or 0),
            'time': f"{item.get('ord_dt', '')} {item.get('ord_tmd', '')}",
        })
    return fills


def get_daily_executions(from_date: str | None = None, to_date: str | None = None,
                          odno: str = '') -> list[dict]:
    """당일(또는 지정 기간) 실제 체결 내역을 KIS에서 직접 조회한다.

    반환: [{odno, code, name, side, price, qty, amount, time}, ...]
    조회 실패(토큰·계좌 미설정·HTTP 오류)는 빈 리스트를 반환한다 — fail-quiet.
    호출부가 "실측이 없다"와 "실측이 0건이다"를 구분할 필요가 있다면 이 함수
    대신 예외를 잡아 별도로 판정할 것(현재 소비자는 아직 없음).
    """
    return _request_executions(from_date, to_date, odno) or []


def find_execution_by_odno(odno: str, from_date: str | None = None,
                            to_date: str | None = None) -> dict | None:
    """특정 주문번호의 실제 체결 1건을 찾는다. 못 찾으면(미체결·조회실패) None."""
    if not odno or odno == 'UNKNOWN':
        return None
    fills = get_daily_executions(from_date, to_date, odno=odno)
    for f in fills:
        if f['odno'] == odno:
            return f
    return None


def lookup_execution(odno: str, from_date: str | None = None,
                      to_date: str | None = None) -> tuple[str, dict | None]:
    """주문번호 하나의 체결 상태. ('filled', fill) | ('unfilled', None) | ('unknown', None)"""
    if not odno or odno == 'UNKNOWN':
        return UNKNOWN, None
    rows = _request_executions(from_date, to_date, odno=odno)
    if rows is None:
        return UNKNOWN, None
    for f in rows:
        if f.get('odno') == odno:
            return FILLED, f
    return UNFILLED, None
