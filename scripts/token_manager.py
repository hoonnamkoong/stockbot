import os
import json
import requests
import time
import sys
from datetime import datetime, timedelta

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# KIS 토큰 관리 전담 모듈 (V51 비공개 저장소 단일 발급자)
# [Role] 토큰의 유일한 발급자. token_refresh.yml(평일 장전 스케줄 + 온디맨드)이 구동.
# [Policy] 토큰은 public db-data가 아닌 비공개 레포 stockbot-secret에 보관한다.
#          Vercel/스크래퍼는 이 비공개 레포를 인증해 읽기만 한다.

import base64

TOKEN_CACHE_PATH = 'data/kis_token_cache.json'  # 런타임 내 로컬 캐시(부차적)

# [Security] 토큰 단일 보관처: 비공개 레포
SECRET_OWNER = 'hoonnamkoong'
SECRET_REPO = 'stockbot-secret'
SECRET_BRANCH = 'main'
SECRET_TOKEN_PATH = 'kis_token_cache.json'


def _gh_token():
    return os.environ.get('GH_PAT') or os.environ.get('GITHUB_PAT') or os.environ.get('GITHUB_TOKEN')


def _secret_api_url():
    return f"https://api.github.com/repos/{SECRET_OWNER}/{SECRET_REPO}/contents/{SECRET_TOKEN_PATH}"


def get_current_kst_time():
    from datetime import timezone
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9)))

def load_token_cache():
    """비공개 레포에서 토큰을 읽는다. 실패 시 로컬 캐시로 폴백."""
    gh = _gh_token()
    if gh:
        try:
            headers = {"Authorization": f"token {gh}", "Accept": "application/vnd.github.raw+json"}
            res = requests.get(f"{_secret_api_url()}?ref={SECRET_BRANCH}", headers=headers, timeout=8)
            if res.status_code == 200:
                return res.json()
            elif res.status_code == 404:
                print("[TokenManager] 비공개 레포에 토큰 없음(최초 발급 필요).")
            else:
                print(f"[TokenManager] 비공개 레포 읽기 실패: {res.status_code}")
        except Exception as e:
            print(f"[TokenManager] 비공개 레포 읽기 오류: {e}")
    else:
        print("[TokenManager] ⚠️ GH_PAT 없음 → 비공개 레포 접근 불가.")
    # 폴백: 로컬 캐시
    if os.path.exists(TOKEN_CACHE_PATH):
        try:
            with open(TOKEN_CACHE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return None

def save_token_cache(token_data):
    # 발급 시각 기록 추가
    token_data['issued_at'] = get_current_kst_time().isoformat()
    # KIS expires_in은 보통 86400초(24시간)
    expires_in = int(token_data.get('expires_in', 86400))
    token_data['expires_at'] = (get_current_kst_time() + timedelta(seconds=expires_in)).isoformat()

    # 런타임 내 재사용을 위한 로컬 캐시
    os.makedirs('data', exist_ok=True)
    with open(TOKEN_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(token_data, f, indent=2, ensure_ascii=False)

    # 단일 진실원천: 비공개 레포에 즉시 기록
    _push_token_to_secret(token_data)
    print(f"[TokenManager] * 토큰 저장 완료 (비공개 레포 동기화 포함)")


def _push_token_to_secret(token_data):
    gh = _gh_token()
    if not gh:
        print("[TokenManager] ⚠️ GH_PAT 없음 → 비공개 레포 기록 생략(로컬만).")
        return False
    headers = {"Authorization": f"token {gh}", "Accept": "application/vnd.github+json"}
    try:
        sha = None
        res_get = requests.get(f"{_secret_api_url()}?ref={SECRET_BRANCH}", headers=headers, timeout=8)
        if res_get.status_code == 200:
            sha = res_get.json().get('sha')
        content_b64 = base64.b64encode(
            json.dumps(token_data, indent=2, ensure_ascii=False).encode('utf-8')
        ).decode('utf-8')
        payload = {
            "message": f"chore: KIS token {get_current_kst_time().strftime('%Y-%m-%d %H:%M')} KST",
            "content": content_b64,
            "branch": SECRET_BRANCH,
        }
        if sha:
            payload["sha"] = sha
        res_put = requests.put(_secret_api_url(), headers=headers, json=payload, timeout=8)
        if res_put.status_code in (200, 201):
            print(f"[TokenManager] * 비공개 레포 동기화 성공: {SECRET_REPO}/{SECRET_TOKEN_PATH}")
            return True
        print(f"[TokenManager] ❌ 비공개 레포 기록 실패: {res_put.status_code} {res_put.text[:200]}")
    except Exception as e:
        print(f"[TokenManager] ❌ 비공개 레포 기록 오류: {e}")
    return False

def issue_new_token():
    """한국투자증권 API를 통해 새로운 접근 토큰을 발급받습니다."""
    print("[TokenManager] * KIS에 새 토큰 발급 요청 중...")
    
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
        expires_at_str = cache.get('expires_at', '').replace('Z', '+00:00')
        expires_at = datetime.fromisoformat(expires_at_str)
        
        # If naive, assume it's KST (which was the old behavior)
        if expires_at.tzinfo is None:
            from datetime import timezone
            expires_at = expires_at.replace(tzinfo=timezone(timedelta(hours=9)))
            
        if get_current_kst_time() + timedelta(hours=2) < expires_at:
            return True
    except Exception as e:
        print(f"[TokenManager] 검증 오류: {e}")
        pass
    return False

def manage():
    print(f"\n[TokenManager] --- KIS 토큰 상태 점검 ({get_current_kst_time().strftime('%Y-%m-%d %H:%M:%S')} KST) ---")
    
    # 강제 갱신 모드 여부 (Vercel에서 요청 시)
    force_refresh = os.environ.get('FORCE_TOKEN_REFRESH', 'false').lower() == 'true'
    
    cache = load_token_cache()
    
    if not force_refresh and is_token_valid(cache):
        print("[TokenManager] * 기존 토큰이 아직 유효합니다. (발급 스킵)")
        return True
    
    # 토큰 발급 시도
    new_token = issue_new_token()
    if new_token:
        save_token_cache(new_token)
        if force_refresh:
            print("[TokenManager] * 강제 갱신 완료. 작업을 종료합니다.")
            sys.exit(0) # 갱신 모드일 때는 여기서 종료
        return True
    
    print("[TokenManager] ❌ 토큰 관리 실패")
    return False

if __name__ == "__main__":
    if not manage():
        sys.exit(1)
