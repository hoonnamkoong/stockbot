import requests
import os
import json

def test_balance_direct():
    # Hardcoded values from your environment
    app_key = 'XamjjJUQ0x1B9BcneFKHhEh2'
    app_secret = 'LbC0z0ZFNrrFe56hueWBO2DkOdOJdvDfjHFkse3SWtq/3BHnI0JaddVy5pHVIjSPgrqFUB6+JYSx6B6YIGXbHFwgpdjjxHhHBQS/zDhfJ/PrEavkZpIBE5Gjp82+gWXnI6t0hRXrHoxP0pTgMHOQN6nXM/BK7iUmLrWWu0nx9oPv6rR2qYk='
    acc_no = '50158945-01'
    token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJ0b2tlbiIsImF1ZCI6ImZkODU3M2UyLTY2ZWQtNGMyNS1hNmE0LTE3NzJhMjI5NGYwMyIsInByZHRfY2QiOiIiLCJpc3MiOiJ1bm9ndyIsImV4cCI6MTc3MzgwMTY4MSwiaWF0IjoxNzczNzE1MjgxLCJqdGkiOiJQUzJRbDdLREdEbmtYYW1qakpVUTB4MUI5QmNuZUZLSGhFaDIifQ.KIx5bex1Meo8-yGLXe5fnke73dZHB8lEV1FJXmAIJ5diJkwGIAya_bwxFvTwQCYBTXzg-SmgMPMg_-aDBf0avA"
    
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/trading/inquire-balance"
    cano, prdt = acc_no.split('-')
    
    headers = {
        'authorization': f'Bearer {token}',
        'appkey': app_key,
        'appsecret': app_secret,
        'tr_id': 'TTTC8434R',
        'custtype': 'P',
        'content-type': 'application/json'
    }
    params = {
        'CANO': cano,
        'ACNT_PRDT_CD': prdt,
        'AFHR_FLPR_YN': 'N',
        'OFL_YN': 'N',
        'INQR_DVSN': '01',
        'UNPR_DVSN': '01',
        'FUND_STTL_ICLD_YN': 'N',
        'FNCG_AMT_AUTO_RDPT_YN': 'N',
        'PRCS_DVSN': '00',
        'CTX_AREA_FK100': '',
        'CTX_AREA_NK100': ''
    }
    
    print(f"Requesting balance for {acc_no}...")
    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        print(f"Status Code: {res.status_code}")
        data = res.json()
        print(f"Message: {data.get('msg1')}")
        if data.get('output2'):
            print(f"✅ Balance Found: {data.get('output2')[0].get('dnca_tot_amt')} KRW")
        else:
            print(f"❌ No output2 data. Full response: {json.dumps(data, indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    test_balance_direct()
