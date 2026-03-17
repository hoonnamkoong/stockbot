import requests
import json
import os
import time

# Load env manually to avoid dependency on python-dotenv for now
def load_env(env_path=None):
    if env_path is None:
        # Default to .env in the same directory as this script
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

    if not os.path.exists(env_path):
        print(f"Error: .env file not found at {env_path}")
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
    
    # Path to shared token file (sync with src/lib/kis-api.ts)
    # Check multiple possible locations for robust path resolution
    possible_paths = [
        os.path.join(os.getcwd(), 'data', 'kis_token.json'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'kis_token.json'),
        os.path.join(os.getcwd(), 'kis_token.json')
    ]
    
    token_path = possible_paths[0]
    for p in possible_paths:
        if os.path.exists(p):
            token_path = p
            break
    
    # 1. Try to read from file
    data = None
    if os.path.exists(token_path):
        try:
            with open(token_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"Failed to read local token cache: {e}")

    # 2. If local missing or expired, try GitHub (Directly via URL if possible, or skip)
    if not data:
        print("Local token cache missing. Trying GitHub...")
        try:
            # We can try the raw URL first. If it's private, this might fail without auth.
            # But the actions often have GITHUB_TOKEN.
            repo_owner = "hoonnamkoong"
            repo_name = "stockbot"
            branch = "db-data"
            gh_url = f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/{branch}/data/kis_token.json"
            
            headers = {}
            # If in GitHub Actions, we might have GITHUB_TOKEN
            gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT")
            if gh_token:
                headers["Authorization"] = f"token {gh_token}"
            
            res = requests.get(gh_url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                print("Successfully fetched token cache from GitHub.")
                # Save locally for next time
                try:
                    os.makedirs(os.path.dirname(token_path), exist_ok=True)
                    with open(token_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2)
                except: pass
        except Exception as e:
            print(f"Failed to fetch from GitHub: {e}")

    # 3. Validate Token
    if data:
        try:
            access_token = data.get('access_token')
            expires_at_str = data.get('expires_at')
            if access_token and expires_at_str:
                # KIS tokens are valid for 24 hours. 
                # We use a 23-hour buffer to ensure we only get ONE token per day.
                # This matches the TypeScript implementation in src/lib/kis-api.ts
                expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                
                # If cached token was issued less than 23 hours ago, reuse it.
                # Note: KIS doesn't provide issue_at, so we assume expires_at is issue_at + 24h
                # Actually, let's just use the absolute expiry with a 1-hour margin for safety.
                if datetime.now().astimezone() < expires_at - timedelta(hours=1):
                    print(f"Using persistent token (Valid until: {expires_at_str})")
                    return access_token
                else:
                    print("Cached token expired (or within 1h margin).")
        except Exception as e:
            print(f"Token validation failed: {e}")

    # 4. Request new token
    if not app_key or not app_secret:
        print("Error: credentials missing in .env")
        return None

    # Determine URL (Real vs Virtual)
    url = f"{base_url}/oauth2/tokenP"
    headers = { "content-type": "application/json" }
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret
    }
    
    print(f"Requesting new token from KIS ({'Virtual' if 'vts' in base_url.lower() else 'Real'})...")
    try:
        res = requests.post(url, headers=headers, data=json.dumps(body), timeout=10)
        if res.status_code == 200:
            data = res.json()
            access_token = data.get('access_token')
            expires_in = data.get('expires_in', 86400) # 24 hours
            
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
                    
                print(f"Success! New Access Token retrieved and saved to {token_path}.")
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
