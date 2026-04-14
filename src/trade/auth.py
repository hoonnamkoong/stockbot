import os
import requests
import json
import base64
from datetime import datetime, timedelta, timezone
try:
    from dotenv import load_dotenv
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False

# [Rule 4.3] KIS API 인증 및 토큰 관리를 위한 모듈입니다.
# 토큰의 수명을 관리하고 깃허브 원격 저장소와 동기화하여 다중 환경(Actions, Vercel 등)에서 동일한 세션을 유지합니다.

def load_env():
    """시스템 환경 변수를 로드합니다."""
    # [Why] 서버 환경(GitHub Actions 등)에는 이미 환경 변수가 주입되어 있으므로, 
    # 로컬 개발 환경에서만 .env 파일을 선택적으로 로드합니다.
    if HAS_DOTENV and os.path.exists('.env'):
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

        # [Step 3] 가져온 토큰의 유효성 검증 (UTC 절대 시간 기준)
        if data:
            try:
                access_token = data.get('access_token')
                issued_at_str = data.get('issued_at')
                expires_at_str = data.get('expires_at')
                
                if access_token:
                    # 모든 비교는 타임존이 포함된 UTC 기준으로 정규화
                    now = datetime.now().astimezone()
                    
                    if expires_at_str:
                        expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                        # 만료 시간까지 2시간 이상 여유가 있는 경우에만 재사용 (안전 마진)
                        time_left = (expires_at - now).total_seconds()
                        
                        if time_left > 7200: # 2시간
                            print(f"[Auth] 유효한 캐시 토큰 발견 (남은 시간: {time_left/3600:.1f}시간)")
                            return access_token
                        else:
                            print(f"[Auth] 캐시 토큰 만료 임박 ({time_left/3600:.1f}시간 남음) -> 갱신 시도")
                    elif issued_at_str:
                        # 하위 호환성: 만료 정보가 없으면 발행 시간 기준 23시간 이내인지 확인
                        issued_at = datetime.fromisoformat(issued_at_str.replace('Z', '+00:00'))
                        if (now - issued_at).total_seconds() < 82800: # 23시간
                            print(f"[Auth] 발행 기준 유효 토큰 재사용 중 ({issued_at_str})")
                            return access_token
            except Exception as e:
                print(f"[Auth] 토큰 검증 오류: {e}")
        
        if not gh_token and not os.path.exists(token_path):
             print("[Auth] ⚠️ 경고: GH_PAT 환경 변수가 없어 GitHub 연동 캐시를 사용할 수 없습니다. Vercel 설정을 확인하세요.")
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
                
                # [V8.9.9.22 Persistence] 깃허브 원격 저장소에 즉시 동기화하여 중복 발급 방지
                _update_github_token_cache(token_data)
                
                return access_token
        else:
            print(f"[Auth] KIS API 오류 {res.status_code}: {res.text}")
    except Exception as e:
        print(f"[Auth] 토큰 발급 예외 발생: {e}")
        
    return None

def _update_github_token_cache(token_data):
    """실시간으로 발급된 토큰을 GitHub db-data 브랜치에 동기화합니다."""
    gh_token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
    if not gh_token:
        print("[Auth] Skip: GH_PAT가 없어 원격 동기화를 수행하지 않습니다.")
        return False

    repo_owner = "hoonnamkoong"
    repo_name = "stockbot"
    branch = "db-data"
    gh_file_path = "data/kis_token_cache.json"
    
    api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{gh_file_path}"
    headers = {
        "Authorization": f"token {gh_token}",
        "Accept": "application/vnd.github.v3+json"
    }

    try:
        # 1. 기존 파일의 SHA 값 획득 (업데이트를 위해 필수)
        res_get = requests.get(api_url + f"?ref={branch}", headers=headers, timeout=5)
        sha = None
        if res_get.status_code == 200:
            sha = res_get.json().get('sha')

        # 2. 파일 업데이트 실행
        content_b64 = base64.b64encode(json.dumps(token_data, indent=2).encode('utf-8')).decode('utf-8')
        payload = {
            "message": f"[V8.9.9.22] Sync KIS Token: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "content": content_b64,
            "branch": branch
        }
        if sha:
            payload["sha"] = sha

        res_put = requests.put(api_url, headers=headers, json=payload, timeout=5)
        if res_put.status_code in [200, 201]:
            print(f"[Auth] GitHub 원격 동기화 성공: {gh_file_path} ({branch})")
            return True
        else:
            print(f"[Auth] GitHub 동기화 실패: {res_put.status_code} {res_put.text}")
    except Exception as e:
        print(f"[Auth] GitHub 동기화 중 오류 발생: {e}")
    
    return False

def get_account_info():
    """
    [지시사항] KIS 계좌번호(KIS_ACCOUNT_NO)를 읽어 CANO(8자리)와 ACNT_PRDT_CD(2자리)로 분리합니다.
    [Why] 한국투자증권 API는 계좌번호를 두 부분으로 나누어 수신하기 때문입니다.
    """
    load_env()
    account_full = os.environ.get('KIS_ACCOUNT_NO', '').strip().replace("-", "") # 하이픈 제거 후 처리
    cano = ""
    acnt_prdt_cd = ""

    if account_full:
        if len(account_full) >= 10:
            # 표준 규격: 앞 8자리 계좌번호 + 뒤 2자리 상품코드
            cano = account_full[:8]
            acnt_prdt_cd = account_full[8:10]
        else:
            # 예외 상황 처리 (로그 기록)
            print(f"[Auth] 경고: 계좌번호 형식이 올바르지 않습니다 (길이: {len(account_full)})")
            
    return cano, acnt_prdt_cd

def get_base_url():
    """실전/모의 서버 주소를 반환합니다."""
    load_env()
    is_virtual = os.environ.get("KIS_IS_VIRTUAL", "false").lower() == "true"
    if is_virtual:
        return "https://openapivts.koreainvestment.com:29443"
    return "https://openapi.koreainvestment.com:9443"

if __name__ == "__main__":
    t = get_access_token()
    if t: print(f"[Auth] 최종 토큰 획득 성공 (길이={len(t)})")
    else: print("[Auth] 토큰 획득 실패")
