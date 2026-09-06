import os
import requests
import json
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

def _is_data_valid(data: dict) -> bool:
    """토큰 dict의 만료 여부를 빠르게 확인. 만료/파싱오류 → False."""
    try:
        token = data.get('access_token')
        expires_at_str = data.get('expires_at')
        if not token or not expires_at_str:
            return False
        expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone(timedelta(hours=9)))
        return (expires_at - datetime.now().astimezone()).total_seconds() > 7200
    except Exception:
        return False


def get_access_token(force_refresh=False):
    """한국투자증권(KIS) API 접속용 OAuth2 토큰을 **가져옵니다**(발급하지 않습니다).

    로컬 캐시 → 비공개 레포 순으로 읽고, 둘 다 못 쓰면 유일 발급자
    (scripts/token_manager.py)에게 맡깁니다. 발급 가드가 전부 거기 있으므로
    이 함수가 직접 KIS에 발급을 요청하는 경로는 없습니다.
    """
    load_env()
    
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
    # [Security] 토큰은 public이 아닌 비공개 레포에 보관(인증 필요)
    repo_owner = "hoonnamkoong"
    repo_name = "stockbot-secret"
    branch = "main"
    gh_file_path = "kis_token_cache.json"

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

        # [Step 2] 로컬 캐시가 없거나 만료됐으면 비공개 레포(stockbot-secret)에서 읽기 시도
        _local_expired = data is not None and not _is_data_valid(data)
        if (not data or _local_expired) and gh_token:
            if _local_expired:
                print("[Auth] 로컬 캐시 만료됨. 비공개 레포 확인 중...")
            else:
                print("[Auth] 로컬 캐시 없음. 비공개 레포 확인 중...")
            try:
                gh_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{gh_file_path}?ref={branch}"
                headers = {"Authorization": f"token {gh_token}", "Accept": "application/vnd.github.raw+json"}
                res = requests.get(gh_url, headers=headers, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    print("[Auth] 비공개 레포에서 최신 토큰 동기화 성공.")
                    # 다음 로드를 위해 로컬에 저장
                    try:
                        os.makedirs(os.path.dirname(token_path), exist_ok=True)
                        with open(token_path, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=2)
                    except: pass
            except Exception as e:
                print(f"[Auth] GitHub 동기화 실패: {e}")

        # [Step 3] 가져온 토큰의 유효성 검증
        if data and _is_data_valid(data):
            access_token = data.get('access_token')
            try:
                expires_at = datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00'))
                time_left = (expires_at - datetime.now().astimezone()).total_seconds()
                print(f"[Auth] 유효한 캐시 토큰 발견 (남은 시간: {time_left/3600:.1f}시간)")
            except Exception:
                pass
            return access_token
        
        if not gh_token and not os.path.exists(token_path):
             print("[Auth] ⚠️ 경고: GH_PAT 환경 변수가 없어 GitHub 연동 캐시를 사용할 수 없습니다. Vercel 설정을 확인하세요.")
    else:
        print("[Auth] 토큰 강제 갱신 요청됨.")

    # [Step 4] 캐시가 없거나 유효하지 않다 — **여기서 발급하지 않는다.**
    #
    # 발급자는 scripts/token_manager.py 하나이고, 가드도 거기에만 있다:
    # 형제 발급 창 10분 / 강제 갱신 최소 간격 30분 / 저장소에 못 닿으면 발급 보류 /
    # 네트워크 재시도 3회. 이 파일이 자기 힘으로 발급하던 시절에는 그중 하나도
    # 없어서 **"원격 읽기가 5초 안에 안 끝난 것"과 "토큰이 만료된 것"이 같은
    # 결과**를 냈다 — 2026-06-05(스크래퍼 하루 7회)과 2026-09-04(프리마켓 매 런)
    # 두 번의 토큰 폭주가 그것이다.
    #
    # 지연 import: token_manager는 import 시점에 win32에서 stdout을 교체한다.
    try:
        from scripts.token_manager import ensure_valid_token
    except ImportError as e:
        print(f"[Auth] 발급자 모듈을 불러올 수 없습니다: {e}")
        return None

    issued = ensure_valid_token(force_refresh=force_refresh)
    if not issued:
        # 발급자가 "지금 발급하면 안 된다"고 판단한 경우가 포함된다. 여기서
        # 뒤집으면 가드를 넷 만든 의미가 없다.
        print("[Auth] 유일 발급자가 토큰을 확보하지 못했습니다 — 자체 발급하지 않습니다.")
        return None
    return issued.get('access_token')


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
