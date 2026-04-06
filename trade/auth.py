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
        pass # 파일이 없으면 에러를 뱉지 말고 자연스럽게 넘어감
        return
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            if '=' in line:
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip()

from datetime import datetime, timedelta, timezone

def get_access_token(force_refresh=False):
    load_env()
    
    app_key = os.environ.get("KIS_APP_KEY", "").strip().replace("\n", "")
    app_secret = os.environ.get("KIS_APP_SECRET", "").strip().replace("\n", "")
    is_virtual = os.environ.get("KIS_IS_VIRTUAL", "false").lower() == "true"
    
    default_url = "https://openapi.koreainvestment.com:9443" if not is_virtual else "https://openapivts.koreainvestment.com:29443"
    base_url = os.environ.get("KIS_BASE_URL", default_url)
    
    # Path to shared token file (sync with src/lib/kis-api.ts)
    possible_paths = [
        os.path.join(os.getcwd(), 'data', 'kis_token_cache.json'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'kis_token_cache.json'),
        os.path.join(os.getcwd(), 'kis_token_cache.json')
    ]
    
    token_path = possible_paths[0]
    for p in possible_paths:
        if os.path.exists(p):
            token_path = p
            break
    
    data = None
    gh_token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
    repo_owner = "hoonnamkoong"
    repo_name = "stockbot"
    branch = "db-data"
    gh_file_path = "data/kis_token_cache.json"

    if not force_refresh:
        # 1. Try to read from local file FIRST
        for p in possible_paths:
            if os.path.exists(p):
                try:
                    if os.path.exists(p) and os.path.getsize(p) > 0:
                        with open(p, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            print(f"Checking token from local cache: {p}")
                            break
                    else:
                        if os.path.exists(p):
                            print(f"Token file {p} is empty. Skipping cache.")
                except Exception as e:
                    print(f"Failed to read local token cache at {p}: {e}")

        # 2. If local missing, try GitHub (Only as a fallback)
        if not data:
            print("Local token cache missing. Trying GitHub...")
            try:
                gh_url = f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/{branch}/{gh_file_path}"
                
                headers = {}
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
                else:
                    print(f"GitHub fetch failed: Status {res.status_code}")
            except Exception as e:
                print(f"Failed to fetch from GitHub: {e}")

        # 3. Validate Token: Check if issued TODAY
        if data:
            try:
                access_token = data.get('access_token')
                issued_at_str = data.get('issued_at')
                expires_at_str = data.get('expires_at')
                
                if access_token:
                    now = datetime.now().astimezone()
                    
                    # Policy 1: If issued today (calendar date), reuse it.
                    if issued_at_str:
                        issued_at = datetime.fromisoformat(issued_at_str.replace('Z', '+00:00'))
                        if issued_at.date() == now.date():
                            print(f"Using token issued TODAY ({issued_at_str})")
                            return access_token
                    
                    # Policy 2: Fallback to expiry check if issued_at is missing
                    if expires_at_str:
                        expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                        if now < expires_at - timedelta(hours=1):
                            print(f"Using persistent token (Valid until: {expires_at_str})")
                            return access_token
                    
                if not access_token:
                    print("No valid access_token found in cache.")
                else:
                    print("Cached token was either issued on a different day or is near expiry.")
            except Exception as e:
                print(f"Token validation failed: {e}")
    else:
        print("Force-refresh requested. Requesting new token from KIS...")

    # 4. Request new token
    if not app_key or not app_secret:
        print("Error: KIS credentials missing in environment variables.")
        # [디버깅 강화] KIS 관련 환경 변수 목록 출력
        kis_keys = {k: ("HIDDEN" if v else "EMPTY") for k, v in os.environ.items() if k.startswith("KIS_")}
        print(f"[Debug] 현재 KIS 관련 환경 변수 상태: {kis_keys}")
        if 'KIS_APP_KEY' not in os.environ:
            print("[Debug] 'KIS_APP_KEY' 자체가 os.environ에 없습니다. (GitHub Actions env 블록 누락 의심)")
        return None

    # Determine URL (Real vs Virtual)
    url = f"{base_url}/oauth2/tokenP"
    
    # [긴급 지시] 확실한 헤더 명시 및 JSON 전송 규격화
    headers = { 
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json"
    }
    payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret
    }
    
    print(f"Requesting NEW token from KIS ({'Virtual' if 'vts' in base_url.lower() else 'Real'})...")
    print(f"[Debug] Request URL: {url}")
    try:
        # data=json.dumps 대신 더 안전하고 권장되는 json= 파라미터 사용
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        
        # [긴급 지시] 응답 본문 강제 노출
        print(f"[Debug] KIS Response Status: {res.status_code}")
        print(f"[Debug] KIS Response Text: {res.text}")

        if res.status_code == 200:
            try:
                data = res.json()
            except Exception as json_err:
                # [로직 방어] HTML 반환 시 가시적인 원인 분석 노출
                if "<html" in res.text.lower() or "<h1>error" in res.text.lower():
                    print(f"[Debug] ❌ KIS 서버 게이트웨이 에러: 요청 포맷 또는 IP 차단 의심")
                print(f"[Debug] ❌ JSON 파싱 에러 발생: {json_err}. 위 Response Text를 확인하세요.")
                return None
                
            access_token = data.get('access_token')
            expires_in = data.get('expires_in', 86400) # 通常 24 hours
            
            if access_token:
                now = datetime.now().astimezone()
                expires_at = now + timedelta(seconds=expires_in)
                token_data = {
                    "access_token": access_token,
                    "issued_at": now.isoformat(),
                    "expires_at": expires_at.isoformat()
                }
                
                # Ensure data dir exists
                os.makedirs(os.path.dirname(token_path), exist_ok=True)
                
                # Double-check structure before saving
                if access_token and len(access_token) > 20:
                    with open(token_path, 'w', encoding='utf-8') as f:
                        json.dump(token_data, f, indent=2)
                    print(f"Success! New Access Token retrieved and saved to {token_path}.")
                    return access_token
                else:
                    raise ValueError("Invalid access_token received from KIS")
            else:
                print(f"Failed to extract access_token from response: {data}")
        else:
            print(f"KIS API Error {res.status_code}: {res.text}")
            
    except Exception as e:
        print(f"Token Fetch Exception: {e}")
        
    return None
        
    return None

if __name__ == "__main__":
    print("Testing KIS Authentication...")
    token = get_access_token()
    if token:
        print("✅ Authentication Test Passed.")
    else:
        print("❌ Authentication Failed.")
