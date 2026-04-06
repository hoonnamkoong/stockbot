import os
import sys
import json
from datetime import datetime

# 프로젝트 루트 경로 추가 (src 패키지 인식 보장)
root_dir = os.getcwd()
if root_dir not in sys.path:
    sys.path.append(root_dir)

# 운영 모듈 임포트
from src.trade.auth import get_access_token, load_env
from src.trade.balance import get_balance

def test_kis_v2_diagnostic():
    print("\n" + "="*60)
    print("🚀 [KIS Diagnostic Test v2] Starting...")
    print(f"⏰ Execution Time (Local): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    # 1. 환경 변수 로드 및 점검
    load_env()
    app_key = os.environ.get("KIS_APP_KEY", "")
    is_virtual = os.environ.get("KIS_IS_VIRTUAL", "false").lower() == "true"
    base_url = os.environ.get("KIS_BASE_URL", "")
    account_no = os.environ.get("KIS_ACCOUNT_NO", "")

    print(f"📊 Mode: {'[VIRTUAL/MOCK]' if is_virtual else '[REAL/REAL-ACCOUNT]'}")
    print(f"📊 Base URL: {base_url}")
    print(f"📊 App Key: {app_key[:5]}*****")
    print(f"📊 Account No: {account_no[:8]}-**")
    print("-" * 60)

    # 2. 인증 테스트 (Token Issuance)
    print("\n[Step 1] Requesting/Verifying Access Token...")
    try:
        token = get_access_token()
        if token:
            print(f"✅ Token verified successfully (Length: {len(token)})")
        else:
            print("❌ Failed to get access token. Check your AppKey/Secret.")
            return
    except Exception as e:
        print(f"❌ Exception during Auth: {e}")
        return

    # 3. 잔고 조회 테스트 (Balance Inquiry)
    print("\n[Step 2] Fetching Balance & Portfolio (Real-time)...")
    try:
        # get_balance() 호출 (내부에 상세 로깅이 포함되어 있음)
        result = get_balance()
        
        if result:
            print("\n" + "-"*30 + " [DIAGNOSTIC SUMMARY] " + "-"*30)
            print(f"💰 Total Equity (평가금액): {result.get('total_equity', 0):,.0f} KRW")
            print(f"💰 Cash Balance (예수금): {result.get('cash', 0):,.0f} KRW")
            
            holdings = result.get('holdings', [])
            print(f"📈 Holdings Count: {len(holdings)}")
            
            for i, h in enumerate(holdings[:5]): # 상위 5개만 출력 (보안)
                print(f"   [{i+1}] {h.get('name', 'Unknown')}: {h.get('qty', 0)} shares / {h.get('price', 0):,.0f} KRW")
            
            if len(holdings) > 5:
                print(f"   ... and {len(holdings)-5} more.")
                
            print("-" * 82)
            print("✅ [Conclusion] KIS Connection is STABLE locally.")
        else:
            print("❌ [Conclusion] KIS Connection returned EMPTY result. Check parameters/permissions.")
            
    except Exception as e:
        print(f"❌ Critical failure during Balance Fetch: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_kis_v2_diagnostic()
