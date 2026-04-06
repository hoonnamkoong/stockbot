import os
import json
import requests
import sys

# [Debug] Manual .env loader (to avoid dependency on python-dotenv)
def load_env_manual(filepath):
    if not os.path.exists(filepath):
        return False
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip().strip("'").strip('"')
    return True

# try root .env first, then trade/.env
if not load_env_manual(".env"):
    if load_env_manual("trade/.env"):
        print("✅ .env loaded manually from trade/.env")
    else:
        print("⚠️ No .env file found in root or trade/ folder")
else:
    print("✅ .env loaded manually from root")

def test_kis_api():
    # 1. Prepare Credentials (strip for safety)
    base_url = os.environ.get("KIS_BASE_URL", "https://openapi.koreainvestment.com:9443").strip()
    app_key = os.environ.get("KIS_APP_KEY", "").strip()
    app_secret = os.environ.get("KIS_APP_SECRET", "").strip()
    account_no = os.environ.get("KIS_ACCOUNT_NO", "").strip()

    print("\n" + "="*50)
    print("🚀 [KIS Connection Test] Initializing...")
    print(f"📊 Target Base URL: {base_url}")
    print(f"📊 App Key (First 5): {app_key[:5]}...")
    print(f"📊 Account No: {account_no}")
    print("="*50)

    if not app_key or not app_secret:
        print("❌ [Critical] KIS_APP_KEY or KIS_APP_SECRET is empty. Check your .env file.")
        sys.exit(1)

    # 🟢 STEP 1: OAuth2 Token Issue
    token_url = f"{base_url}/oauth2/tokenP"
    token_headers = {"Content-Type": "application/json"}
    token_payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret
    }

    print(f"\n[Step 1] Requesting Token...")
    print(f"👉 URL: {token_url}")
    print(f"👉 Headers: {json.dumps(token_headers, indent=2)}")
    
    try:
        res = requests.post(token_url, headers=token_headers, data=json.dumps(token_payload), timeout=10)
        print(f"📥 Response Status: {res.status_code}")
        
        # 가감 없이 원본 출력
        print("-" * 30 + " [BODY] " + "-" * 30)
        print(res.text)
        print("-" * 68)

        if res.status_code != 200:
            print("❌ Token request failed. Stopping test.")
            return

        try:
            token_data = res.json()
            access_token = token_data.get("access_token")
            if not access_token:
                print("❌ 'access_token' not found in JSON response.")
                return
            print("✅ Token successfully issued.")
        except Exception:
            print("❌ Response body is not valid JSON.")
            return

    except Exception as e:
        print(f"❌ Exception during Token request: {e}")
        return

    # 🟢 STEP 2: Inquire Balance (minimal minimal headers)
    balance_url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
    
    # 3/24 버전 하드코딩식 계좌 처리
    clean_acc = account_no.replace("-", "")
    cano = clean_acc[:8]
    acnt_prdt_cd = "01"

    balance_headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "TTTC8434R" if "vts" not in base_url.lower() else "VTTC8434R",
        "custtype": "P"
    }

    params = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }

    print(f"\n[Step 2] Fetching Balance...")
    print(f"👉 URL: {balance_url}")
    print(f"👉 Headers (stripped): { {k:v[:10]+'...' if k=='Authorization' else v for k,v in balance_headers.items()} }")
    print(f"👉 Params: {json.dumps(params, indent=2)}")

    try:
        res = requests.get(balance_url, headers=balance_headers, params=params, timeout=10)
        print(f"📥 Response Status: {res.status_code}")
        
        print("-" * 30 + " [BODY] " + "-" * 30)
        print(res.text)
        print("-" * 68)

        if res.status_code == 200:
            print("✅ Balance API successfully reachable.")
        else:
            print("❌ Balance API returned error state.")

    except Exception as e:
        print(f"❌ Exception during Balance request: {e}")

if __name__ == "__main__":
    test_kis_api()
