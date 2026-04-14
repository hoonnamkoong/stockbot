import os
import json
import requests
import time
import sys
from datetime import datetime, timedelta

# KIS 토큰 관리 전담 모듈 (V8.9.9.39)
# [Role] GitHub Action이 실행될 때 가장 먼저 구동되어 토큰의 유효성을 보장함.
# [Policy] Vercel은 이 파일을 읽기만 하며, 직접 발급하지 않음.

TOKEN_CACHE_PATH = 'data/kis_token_cache.json'

def get_current_kst_time():
    return datetime.utcnow() + timedelta(hours=9)

def load_token_cache():
    if os.path.exists(TOKEN_CACHE_PATH):
        try:
            with open(TOKEN_CACHE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return None

def save_token_cache(token_data):
    os.makedirs('data', exist_ok=True)
    # 발급 시각 기록 추가
    token_data['issued_at'] = get_current_kst_time().isoformat()
    # KIS expires_in은 보통 86400초(24시간)
    expires_in = int(token_data.get('expires_in', 86400))
    token_data['expires_at'] = (get_current_kst_time() + timedelta(seconds=expires_in)).isoformat()
    
    with open(TOKEN_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(token_data, f, indent=2, ensure_ascii=False)
    print(f"[TokenManager] ✅ 토큰 저장 완료: {TOKEN_CACHE_PATH}")

def issue_new_token():
    """한국투자증권 API를 통해 새로운 접근 토큰을 발급받습니다."""
    print("[TokenManager] 🔑 KIS에 새 토큰 발급 요청 중...")
    
    # 깃허브 액션 비밀 키 명칭과 일치시킴
    app_key = os.environ.get('KIS_APP_KEY')
    app_secret = os.environ.get('KIS_APP_SECRET')
    
    if not app_key or not app_secret:
        print("[TokenManager] ❌ 오류: KIS_APP_KEY 또는 KIS_APP_SECRET 환경변수가 없습니다.")
        return None

    url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
    payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret
    }
    
    try:
        # 분당 1회 제한(EGW00133)을 피하기 위해 혹시 모를 짧은 대기
        time.sleep(1)
        res = requests.post(url, json=payload, timeout=10)
        data = res.json()
        
        if 'access_token' in data:
            return data
        else:
            print(f"[TokenManager] ❌ 발급 실패: {data}")
            return None
    except Exception as e:
        print(f"[TokenManager] ❌ 통신 오류: {e}")
        return None

def is_token_valid(cache):
    if not cache or 'access_token' not in cache:
        return False
    
    # 만료 시간 체크 (여유 있게 2시간 전부터 만료로 간주)
    try:
        expires_at = datetime.fromisoformat(cache.get('expires_at'))
        if get_current_kst_time() + timedelta(hours=2) < expires_at:
            return True
    except:
        pass
    return False

def manage():
    print(f"\n[TokenManager] --- KIS 토큰 상태 점검 ({get_current_kst_time().strftime('%Y-%m-%d %H:%M:%S')} KST) ---")
    
    # 강제 갱신 모드 여부 (Vercel에서 요청 시)
    force_refresh = os.environ.get('FORCE_TOKEN_REFRESH', 'false').lower() == 'true'
    
    cache = load_token_cache()
    
    if not force_refresh and is_token_valid(cache):
        print("[TokenManager] ✨ 기존 토큰이 아직 유효합니다. (발급 스킵)")
        return True
    
    # 토큰 발급 시도
    new_token = issue_new_token()
    if new_token:
        save_token_cache(new_token)
        if force_refresh:
            print("[TokenManager] 🚀 강제 갱신 완료. 작업을 종료합니다.")
            sys.exit(0) # 갱신 모드일 때는 여기서 종료
        return True
    
    print("[TokenManager] ❌ 토큰 관리 실패")
    return False

if __name__ == "__main__":
    if not manage():
        sys.exit(1)
