import requests
import json
import os
import sys
import traceback
from auth import get_access_token, load_env

def check_balance():
    # 1. Get Token
    try:
        access_token = get_access_token()
        if not access_token:
            print("[Balance] ❌ Access Token 발급 실패.")
            sys.exit(1)
    except Exception:
        print("[Balance] ❌ 토큰 발급 중 예외 발생")
        traceback.print_exc()
        sys.exit(1)

    # 2. Config
    load_env()
    app_key = os.environ.get("KIS_APP_KEY", "").strip().replace("\n", "")
    app_secret = os.environ.get("KIS_APP_SECRET", "").strip().replace("\n", "")
    account_no_full = os.environ.get("KIS_ACCOUNT_NO", "").strip().replace("\n", "")
    base_url = os.environ.get("KIS_BASE_URL")
    
    if not account_no_full:
        print("[Balance] ❌ KIS_ACCOUNT_NO 환경 변수가 없습니다.")
        sys.exit(1)

    # ─── 계좌번호 파싱 (8자리-2자리 엄격 분리) ───
    clean_acc = account_no_full.replace('-', '').replace(' ', '')
    if len(clean_acc) < 10:
        print(f"[Balance] ❌ 계좌번호 형식이 올바르지 않습니다 (10자리 미만: {account_no_full})")
        sys.exit(1)
        
    cano = clean_acc[:8]
    acnt_prdt_cd = clean_acc[8:10] # 정확히 2자리만 사용

    # Determine TR ID
    is_virtual = "vts" in base_url.lower()
    tr_id = "VTTC8434R" if is_virtual else "TTTC8434R"

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
    
    url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance"

    print(f"\n[Balance] API 호출 시도: {cano}-{acnt_prdt_cd} ({'모의' if is_virtual else '실전'})")
    
    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        
        # HTTP 상태 코드 확인
        if res.status_code != 200:
            print(f"[Balance] ❌ HTTP Error {res.status_code}")
            print(f"Response: {res.text}")
            sys.exit(1)
            
        data = res.json()
        
        # KIS API 로직 응답 확인 (rt_cd)
        if data.get('rt_cd') != '0':
            msg = data.get('msg1', 'Unknown Error')
            code = data.get('msg_cd', 'NoCode')
            print(f"[Balance] ❌ KIS API Error: {msg} (Code: {code})")
            # 상세 응답 본문 출력 (보안 주의: 민감 정보 제거 확인됨)
            sys.exit(1)

        # 성공 시 데이터 처리
        output1 = data.get('output1', [])
        output2 = data.get('output2', [])
        
        print(f"=== Account Summary ===")
        if output2:
            summary = output2[0]
            print(f"Total Asset: {summary.get('tot_evlu_amt', '0')} KRW")
            print(f"Deposit: {summary.get('dnca_tot_amt', '0')} KRW")
            print(f"Total Profit/Loss: {summary.get('evlu_pfls_smtl_amt', '0')} KRW")
        
        print(f"\n=== Holdings ({len(output1)}) ===")
        for item in output1:
            print(f"[{item.get('prdt_name')}] Qty: {item.get('hldg_qty')}, Price: {item.get('prpr')}, P/L: {item.get('evlu_pfls_rt')}%")
            
    except Exception as e:
        print(f"[Balance] ❌ 예상치 못한 예외 발생")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    check_balance()
