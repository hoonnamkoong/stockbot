import os
import requests
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

# [Rule 4.3] KIS API 인증 및 토큰 관리를 위한 모듈입니다.
# 토큰의 수명을 관리하고 깃허브 원격 저장소와 동기화하여 다중 환경(Actions, Vercel 등)에서 동일한 세션을 유지합니다.

def load_env():
    """시스템 환경 변수를 로드합니다."""
    # .env 파일이 존재할 경우 로드 (로컬 개발 환경 대응)
    if os.path.exists('.env'):
        load_dotenv('.env', override=True)

def get_access_token(force_refresh=False):
    """
    한국투자증권(KIS) API 접속을 위한 OAuth2 토큰을 발급하거나 캐시된 토큰을 반환합니다.
    [Why] 1분당 토큰 발급 횟수 제한(1회)을 준수하기 위해 로컬 및 원격 캐시를 우선 확인합니다.
    """
    load_env()
    
    # 환경 변수에서 API 키 정보를 로드 (Rule 4.1에 따라 .env 또는 시스템 변수 활용)
    app_key = os.environ.get("KIS_APP_KEY", "").strip().replace("\n", "")
    app_secret = os.environ.get("KIS_APP_SECRET", "").strip().replace("\n", "")
    is_virtual = os.environ.get("KIS_IS_VIRTUAL", "false").lower() == "true"
    
    # 실전/모의 계좌 주소 구분
    default_url = "https://openapi.koreainvestment.com:9443" if not is_virtual else "https://openapivts.koreainvestment.com:29443"
    base_url = os.environ.get("KIS_BASE_URL", default_url)
    
    # [What] 토큰 공유를 위해 파일명을 대시보드(TypeScript) 코드와 일치시킨 파일 경로 리스트
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
    # 깃허브 연동을 위한 토큰 확인 (GH_PAT 등 다양한 명칭 대응)
    gh_token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
    repo_owner = "hoonnamkoong"
    repo_name = "stockbot"
    branch = "db-data"
    gh_file_path = "data/kis_token_cache.json"

    if not force_refresh:
        # [Step 1] 로컬 캐시 파일에서 토큰 읽기 시도
        for p in possible_paths:
            if os.path.exists(p):
                try:
                    if os.path.exists(p) and os.path.getsize(p) > 0:
                        with open(p, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            print(f"[Auth] 로컬 캐시 토큰 확인: {p}")
                            break
                except Exception as e:
                    print(f"[Auth] 로컬 토큰 로드 실패: {e}")

        # [Step 2] 로컬에 없으면 깃허브 원격 파일(db-data 브랜치)에서 읽기 시도 (동기화 보장)
        if not data:
            print("[Auth] 로컬 캐시 없음. GitHub 원격지 확인 중...")
            try:
                gh_url = f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/{branch}/{gh_file_path}"
                headers = {"Authorization": f"token {gh_token}"} if gh_token else {}
                res = requests.get(gh_url, headers=headers, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    print("[Auth] GitHub에서 최신 토큰 동기화 성공.")
                    # 다음 로드를 위해 로컬에 저장
                    try:
                        os.makedirs(os.path.dirname(token_path), exist_ok=True)
                        with open(token_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2)
                    except: pass
            except Exception as e:
                print(f"[Auth] GitHub 동기화 실패: {e}")

        # [Step 3] 가져온 토큰의 유효성 검증 (당일 발급 여부 및 만료 시간 확인)
        if data:
            try:
                access_token = data.get('access_token')
                issued_at_str = data.get('issued_at')
                expires_at_str = data.get('expires_at')
                
                if access_token:
                    now = datetime.now().astimezone()
                    # KIS 정책상 하루 1회 발급 원칙을 준수하기 위해 '오늘' 날짜인지 확인
                    if issued_at_str:
                        issued_at = datetime.fromisoformat(issued_at_str.replace('Z', '+00:00'))
                        if issued_at.date() == now.date():
                            print(f"[Auth] 오늘 발급된 토큰 재사용 중 ({issued_at_str})")
                            return access_token
                    # 만료 시간 여유 확인
                    if expires_at_str:
                        expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                        if now < expires_at - timedelta(hours=1):
                            print(f"[Auth] 기존 유효 토큰 사용 중 (만료: {expires_at_str})")
                            return access_token
            except Exception as e:
                print(f"[Auth] 토큰 검증 오류: {e}")
    else:
        print("[Auth] 토큰 강제 갱신 요청됨.")

    # [Step 4] 캐시가 없거나 유효하지 않으면 KIS API에 새 토큰 요청
    if not app_key or not app_secret:
        print("[Auth] 오류: KIS 자격 증명(AppKey/Secret)이 없습니다.")
        return None

    url = f"{base_url}/oauth2/tokenP"
    headers = {"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"}
    payload = {"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret}
    
    print(f"[Auth] KIS로부터 새 토큰 발급 시도 ({'모의' if 'vts' in base_url.lower() else '실전'})...")
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        if res.status_code == 200:
            data = res.json()
            access_token = data.get('access_token')
            expires_in = data.get('expires_in', 86400)
            
            if access_token:
                now = datetime.now().astimezone()
                expires_at = now + timedelta(seconds=expires_in)
                token_data = {
                    "access_token": access_token,
                    "issued_at": now.isoformat(),
                    "expires_at": expires_at.isoformat()
                }
                # 신규 토큰 저장
                os.makedirs(os.path.dirname(token_path), exist_ok=True)
                with open(token_path, 'w', encoding='utf-8') as f:
                    json.dump(token_data, f, indent=2)
                
                print(f"[Auth] 새 토큰 저장 완료: {token_path}")
                return access_token
        else:
            print(f"[Auth] KIS API 오류 {res.status_code}: {res.text}")
    except Exception as e:
        print(f"[Auth] 토큰 발급 예외 발생: {e}")
        
    return None

if __name__ == "__main__":
    t = get_access_token()
    if t: print(f"[Auth] 최종 토큰 획득 성공 (길이={len(t)})")
    else: print("[Auth] 토큰 획득 실패")
