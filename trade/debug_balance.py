import requests
import json
import os
from datetime import datetime

# Load env from .env.local if possible, but for now hardcode or assume set
# We'll try to read .env.local manually
env_map = {}
try:
    with open('../.env.local', 'r', encoding='utf-8') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                env_map[k] = v
except:
    pass

APP_KEY = env_map.get('KIS_APP_KEY', '')
APP_SECRET = env_map.get('KIS_APP_SECRET', '')
ACC_NO = env_map.get('KIS_ACCOUNT_NO', '')
BASE_URL = env_map.get('KIS_BASE_URL', 'https://openapivts.koreainvestment.com:29443')

print(f"Testing Balance API with Key: {APP_KEY[:5]}...")

def get_token():
    url = f"{BASE_URL}/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET
    }
    res = requests.post(url, json=body)
    return res.json()['access_token']

try:
    token = get_token()
    print("Token retrieved.")
    
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "VTTC8434R"
    }
    
    params = {
        "CANO": ACC_NO.split('-')[0],
        "ACNT_PRDT_CD": ACC_NO.split('-')[1],
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
    
    url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance"
    print(f"Requesting {url}...")
    
    res = requests.get(url, headers=headers, params=params)
    print(f"Status: {res.status_code}")
    data = res.json()
    if 'output1' in data and len(data['output1']) > 0:
        print("First Holding Keys:", data['output1'][0].keys())
        print("First Holding Data:", data['output1'][0])
    else:
        print("No holdings found or error:", data.get('msg1'))

except Exception as e:
    print(f"Error: {e}")
