import requests
import json
import os
import sys
from auth import get_access_token, load_env

def get_current_price(code="005930"): # Default Samsung Electronics
    access_token = get_access_token()
    if not access_token:
        return

    load_env()
    app_key = os.environ.get("KIS_APP_KEY")
    app_secret = os.environ.get("KIS_APP_SECRET")
    base_url = os.environ.get("KIS_BASE_URL")
    
    url = f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
    
    # TR ID for Domestic Stock Current Price (Same for Mock/Real usually)
    tr_id = "FHKST01010100"

    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P",
    }
    
    params = {
        "FID_COND_MRKT_DIV_CODE": "J", # J: Stock, W: Warrants...
        "FID_INPUT_ISCD": code 
    }
    
    print(f"\n[Price] Fetching price for {code}...")
    
    try:
        res = requests.get(url, headers=headers, params=params)
        
        if res.status_code == 200:
            data = res.json()
            if data['rt_cd'] == '0':
                output = data.get('output', {})
                name = "Unknown" # API doesn't return name in price query usually, only code/price
                # But sometimes it does or we hold it locally.
                # Actually output has 'rprs_mrkt_kor_name' sometimes? No.
                
                price = output.get('stck_prpr') # Current Price
                change = output.get('prdy_vrss') # Change
                rate = output.get('prdy_ctrt') # Rate
                
                print(f"Code: {code}")
                print(f"Price: {price} KRW")
                print(f"Change: {change} ({rate}%)")
                return price
            else:
                print(f"API Error: {data['msg1']} (Code: {data['msg_cd']})")
        else:
            print(f"HTTP Error {res.status_code}: {res.text}")
            
    except Exception as e:
        print(f"Exception: {e}")
        
    return None

if __name__ == "__main__":
    target_code = "005930"
    if len(sys.argv) > 1:
        target_code = sys.argv[1]
    get_current_price(target_code)
