import requests
import json
import os
import sys
import traceback
from auth import get_access_token, load_env

def get_balance():
    """
    KIS API를 사용하여 현재 잔고 및 보유 종목을 가져옵니다.
    임포트하여 사용할 수 있도록 함수화되었습니다.
    """
    access_token = get_access_token()
    if not access_token:
        return {"error": "Failed to get access token", "holdings": []}

    load_env()
    app_key = os.environ.get("KIS_APP_KEY", "").strip().replace("\n", "")
    app_secret = os.environ.get("KIS_APP_SECRET", "").strip().replace("\n", "")
    account_no_full = os.environ.get("KIS_ACCOUNT_NO", "").strip().replace("\n", "")
    is_virtual = os.environ.get("KIS_IS_VIRTUAL", "false").lower() == "true"
    
    default_url = "https://openapi.koreainvestment.com:9443" if not is_virtual else "https://openapivts.koreainvestment.com:29443"
    base_url = os.environ.get("KIS_BASE_URL", default_url)
    
    if not account_no_full:
        return {"error": "Account number missing", "holdings": []}

    clean_acc = account_no_full.replace('-', '').replace(' ', '')
    if len(clean_acc) < 10:
        return {"error": f"Invalid account number: {account_no_full}", "holdings": []}
        
    cano = clean_acc[:8]
    acnt_prdt_cd = clean_acc[8:10]

    tr_id = "VTTC8434R" if is_virtual else "TTTC8434R"
    url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance"

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
        "AFHR_FLG": "N",
        "OCCN_TX_FOR_YN": "N",
        "PRDT_TYPE_CD": "01",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }

    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        if res.status_code != 200:
            return {"error": f"HTTP {res.status_code}: {res.text}", "holdings": []}
            
        data = res.json()
        if data.get('rt_cd') != '0':
            return {"error": f"KIS API Error: {data.get('msg1')} ({data.get('msg_cd')})", "holdings": []}

        output1 = data.get('output1', [])
        output2 = data.get('output2', [{}])[0]
        
        holdings = []
        for item in output1:
            if int(item.get('hldg_qty', 0)) > 0:
                holdings.append({
                    "code": item.get('pdno'),
                    "name": item.get('prdt_name'),
                    "qty": int(item.get('hldg_qty', 0)),
                    "avg_price": float(item.get('pchs_avg_pric', 0)),
                    "current_price": float(item.get('prpr', 0)),
                    "profit_rate": float(item.get('evlu_pfls_rt', 0))
                })
        
        return {
            "deposit": int(output2.get('dnca_tot_amt', 0)),
            "total_asset": int(output2.get('tot_evlu_amt', 0)),
            "total_profit": int(output2.get('evlu_pfls_smtl_amt', 0)),
            "holdings": holdings,
            "raw": data
        }
            
    except Exception as e:
        return {"error": f"Exception: {str(e)}", "holdings": []}

if __name__ == "__main__":
    result = get_balance()
    if "error" in result:
        print(f"❌ {result['error']}")
    else:
        print(f"=== Account Summary ===")
        print(f"Total Asset: {result['total_asset']:,} KRW")
        print(f"Deposit: {result['deposit']:,} KRW")
        
        print(f"\n=== Holdings ({len(result['holdings'])}) ===")
        for h in result['holdings']:
            print(f"[{h['name']}] Qty: {h['qty']}, Price: {h['current_price']:,}, P/L: {h['profit_rate']}%")
