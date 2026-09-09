"""KIS 주문취소(TTTC0803U) — 미체결 주문을 거둔다.

매 사이클 미체결을 취소하고 새 판단가로 다시 내는 구조라, 취소가 실패하면
그 종목에 새 주문을 내지 않는다(중복보다 기회손실이 싸다). 그래서 이 함수의
반환값은 "성공했다고 믿어도 되는가"여야 하고, 애매하면 False다.
"""
import os

import requests

from src.trade.auth import get_access_token, get_base_url


def cancel_order(odno: str, code: str, qty: int) -> bool:
    """미체결 잔량을 전부 취소한다. 성공하면 True.

    주문번호가 없으면 대상을 특정할 수 없으므로 호출하지 않고 False.
    """
    # 그림자 운전(이관 3단계): 폰이 보는 미체결은 **옛 경로가 낸 진짜 주문**이다.
    # 폰이 취소하면 살아 있는 매매를 방해한다 — 주문보다 이쪽이 더 위험하다.
    # 이 경로는 Vercel을 우회해 KIS를 직접 부르므로 WEBHOOK_SECRET 부재로도
    # 막히지 않는다. 여기 가드가 유일한 방어다.
    from src.trade.shadow import is_shadow, refused
    if is_shadow():
        refused('주문취소', f'{code} odno={odno} {qty}주')
        return False

    if not odno or odno == 'UNKNOWN':
        return False
    token = get_access_token()
    if not token:
        return False

    acc = os.environ.get('KIS_ACCOUNT_NO', '').strip().replace('-', '').replace(' ', '')
    if len(acc) < 10:
        return False
    is_virtual = os.environ.get('KIS_IS_VIRTUAL', 'false').lower() == 'true'

    headers = {
        'content-type': 'application/json; charset=utf-8',
        'authorization': f'Bearer {token}',
        'appkey': os.environ.get('KIS_APP_KEY', '').strip(),
        'appsecret': os.environ.get('KIS_APP_SECRET', '').strip(),
        'tr_id': 'VTTC0803U' if is_virtual else 'TTTC0803U',
        'custtype': 'P',
    }
    body = {
        'CANO': acc[:8],
        'ACNT_PRDT_CD': acc[8:10],
        'KRX_FWDG_ORD_ORGNO': '',
        'ORGN_ODNO': odno,
        'ORD_DVSN': '00',
        'RVSE_CNCL_DVSN_CD': '02',   # 02=취소
        'ORD_QTY': str(qty),
        'ORD_UNPR': '0',
        'QTY_ALL_ORD_YN': 'Y',       # 잔량 전부
    }

    try:
        res = requests.post(
            f'{get_base_url()}/uapi/domestic-stock/v1/trading/order-rvsecncl',
            headers=headers, json=body, timeout=10,
        )
        if res.status_code != 200:
            return False
        return res.json().get('rt_cd') == '0'
    except Exception:
        return False
