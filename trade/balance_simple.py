import requests
import json
import os
from auth import get_access_token, load_env

def fetch_balance_data():
    access_token = get_access_token()
    if not access_token: return None

    load_env()
    app_key = os.environ.get("KIS_APP_KEY")
    app_secret = os.environ.get("KIS_APP_SECRET")
    account_no_full = os.environ.get("KIS_ACCOUNT_NO")
    base_url = os.environ.get("KIS_BASE_URL")
    
    clean_acc = account_no_full.replace('-', '')
    cano = clean_acc[:8]
    acnt_prdt_cd = clean_acc[8:]

    url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
    tr_id = "VTTC8434R" 

    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P", 
    }
    
    params = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "N",
        "INQR_DVSN": "02", 
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }
    
    try:
        res = requests.get(url, headers=headers, params=params)
        if res.status_code == 200:
            data = res.json()
            if data['rt_cd'] == '0':
                return data
            else:
                print(f"API Error: {data['msg1']}")
        return None
    except Exception as e:
        print(f"Exception: {e}")
        return None

def show_deposit():
    data = fetch_balance_data()
    if data:
        summary = data.get('output2', [])[0]
        deposit = int(summary.get('dnca_tot_amt', '0'))
        print(f"예수금 (주문 가능 금액): {deposit:,} 원")

def show_holdings():
    data = fetch_balance_data()
    if data:
        holdings = data.get('output1', [])
        print(f"=== 보유 종목 현황 ({len(holdings)}종목) ===")
        for item in holdings:
            name = item.get('prdt_name')
            qty = int(item.get('hldg_qty'))
            price = int(item.get('prpr'))
            pl_rate = float(item.get('evlu_pfls_rt'))
            print(f"- {name}: {qty}주 (현재가: {price:,}원) | 수익률: {pl_rate}%")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "deposit":
            show_deposit()
        elif sys.argv[1] == "holdings":
            show_holdings()
    else:
        show_deposit()
        show_holdings()
