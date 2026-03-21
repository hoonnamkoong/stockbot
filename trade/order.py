import requests
import json
import os
import sys
from auth import get_access_token, load_env

import time

def place_order(side="buy", code="005930", qty=1, price=0):
    """
    side: 'buy' or 'sell'
    price: 0 for Market Price (if supported) or specific price.
    """
    access_token = get_access_token()
    if not access_token:
        raise Exception("Failed to get Access Token")

    load_env()
    app_key = os.environ.get("KIS_APP_KEY")
    app_secret = os.environ.get("KIS_APP_SECRET")
    account_no_full = os.environ.get("KIS_ACCOUNT_NO")
    base_url = os.environ.get("KIS_BASE_URL")
    
    clean_acc = account_no_full.replace('-', '')
    cano = clean_acc[:8]
    acnt_prdt_cd = clean_acc[8:]
    
    url = f"{base_url}/uapi/domestic-stock/v1/trading/order-cash"
    
    # Determine TR ID (Real vs Virtual)
    # Buy: REAL: TTTC0802U, VIRTUAL: VTTC0802U
    # Sell: REAL: TTTC0801U, VIRTUAL: VTTC0801U
    is_virtual = "vts" in base_url.lower()
    if side == "buy":
        tr_id = "VTTC0802U" if is_virtual else "TTTC0802U"
    else:
        tr_id = "VTTC0801U" if is_virtual else "TTTC0801U"

    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P",
        "hashkey": ""
    }
    
    ord_dvsn = "00" 
    if price == 0:
        ord_dvsn = "01" # Market
        
    params = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "PDNO": code,
        "ORD_DVSN": ord_dvsn, 
        "ORD_QTY": str(qty),
        "ORD_UNPR": str(price),
    }
    
    print(f"\n[Order] Placing {side.upper()} Order: {code} x {qty} @ {price}")
    
    # Retry Loop
    max_retries = 5 
    for i in range(max_retries):
        try:
            res = requests.post(url, headers=headers, data=json.dumps(params), timeout=10)
            
            # Handle 401 Unauthorized (Token expired or invalid)
            if res.status_code == 401:
                print(f"Unauthorized (401). Refreshing token and retrying ({i+1}/{max_retries})...")
                access_token = get_access_token(force_refresh=True)
                if not access_token:
                    raise Exception("Failed to refresh access token during 401 retry.")
                headers["authorization"] = f"Bearer {access_token}"
                continue

            data = {}
            try:
                data = res.json()
            except:
                pass

            msg1 = data.get('msg1', '')
            msg_cd = data.get('msg_cd', '')

            # Case A: Success (200 OK + rt_cd '0')
            if res.status_code == 200 and data.get('rt_cd') == '0':
                output = data.get('output', {})
                print(f"Success! Order No: {output.get('ODNO')}")
                print(f"Message: {msg1}")
                return # Success

            # Case B: Rate Limit 
            if '초당' in msg1 or msg_cd in ['EGW00133', 'EGW00201'] or res.status_code == 429:
                print(f"Rate Limit hit ({msg1}). Retrying {i+1}/{max_retries}...")
                time.sleep(1.5 + (i * 0.5)) 
                continue

            # Case C: Known Business Errors
            if data.get('rt_cd') != '0':
                raise Exception(f"API Error: {msg1} (Code: {msg_cd})")

            # Case D: Other HTTP Errors
            raise Exception(f"HTTP Error {res.status_code}: {res.text}")
                
        except Exception as e:
            print(f"Attempt {i+1} Failed: {e}")
            if i < max_retries - 1:
                time.sleep(1)
            else:
               raise e # Re-raise on last failure

if __name__ == "__main__":
    # Default Test: Buy 1 Samsung Electronics at Market Price (or Limit if safer)
    # Mock Market Price often fails if not market hours?
    # Let's try Limit 50000 (Low) just to place order? Or 70000?
    # Or just try Market price (01)
    
    # Note: Market Price might need price=0
    import sys
    side = "buy"
    if len(sys.argv) > 1: side = sys.argv[1]
    
    place_order(side=side, code="005930", qty=1, price=0) # Market Order attempt
