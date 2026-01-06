import requests
import json
import os
import time

# Load env manually to avoid dependency on python-dotenv for now
def load_env(env_path=".env"):
    if not os.path.exists(env_path):
        print("Error: .env file not found.")
        return
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            if '=' in line:
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip()

from datetime import datetime, timedelta

def get_access_token():
    load_env()
    
    app_key = os.environ.get("KIS_APP_KEY")
    app_secret = os.environ.get("KIS_APP_SECRET")
    base_url = os.environ.get("KIS_BASE_URL", "https://openapivts.koreainvestment.com:29443")
    
    # Path to shared token file (sync with src/lib/kis.ts)
    token_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'token.json')
    
    # 1. Try to read from file
    if os.path.exists(token_path):
        try:
            with open(token_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                access_token = data.get('access_token')
                expires_at_str = data.get('expires_at')
                
                if access_token and expires_at_str:
                    # Parse ISO format (e.g., 2026-01-06T10:20:30.000Z)
                    # Python 3.7+ supports fromisoformat, but let's be safe with basic parsing if needed or use dateutil
                    # Simple string comparison works for ISO8601 if in UTC, but safest to parse.
                    # '2026-01-06T10:20:30.000Z' might contain Z.
                    expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                    
                    # Check if valid (buffer 1 min)
                    if datetime.now().astimezone() < expires_at - timedelta(minutes=1):
                        # print("Using cached token")
                        return access_token
                    else:
                        print("Cached token expired.")
        except Exception as e:
            print(f"Failed to read token cache: {e}")

    # 2. Request new token
    if not app_key or not app_secret:
        print("Error: credentials missing in .env")
        return None

    url = f"{base_url}/oauth2/tokenP"
    headers = { "content-type": "application/json" }
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret
    }
    
    try:
        res = requests.post(url, headers=headers, data=json.dumps(body), timeout=10)
        if res.status_code == 200:
            data = res.json()
            access_token = data.get('access_token')
            expires_in = data.get('expires_in', 86400)
            
            if access_token:
                # Save to file
                expires_at = datetime.now().astimezone() + timedelta(seconds=expires_in)
                token_data = {
                    "access_token": access_token,
                    "expires_at": expires_at.isoformat()
                }
                
                # Ensure data dir exists
                os.makedirs(os.path.dirname(token_path), exist_ok=True)
                
                with open(token_path, 'w', encoding='utf-8') as f:
                    json.dump(token_data, f, indent=2)
                    
                print(f"Success! New Access Token retrieved and cached.")
                return access_token
            else:
                print(f"Failed to extract access_token: {data}")
        else:
            print(f"Error {res.status_code}: {res.text}")
            
    except Exception as e:
        print(f"Token Fetch Exception: {e}")
        
    return None

if __name__ == "__main__":
    print("Testing KIS Authentication...")
    token = get_access_token()
    if token:
        print("✅ Authentication Test Passed.")
    else:
        print("❌ Authentication Failed.")
