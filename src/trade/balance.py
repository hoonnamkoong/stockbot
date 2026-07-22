import requests
import json
import os
import sys
import time
import traceback
from src.trade.auth import get_access_token, load_env

# [Rule 4.3] KIS API를 통한 계좌 잔고 및 보유 종목 조회를 담당하는 모듈입니다.
# 실전 및 모의 투자 계좌를 지원하며, 에러 7(조회이후 자료변경) 발생 시의 자동 재시도 로직을 포함합니다.

def _parse_holding(item: dict) -> dict:
    """KIS inquire-balance output1 한 행을 내부 holdings 형식으로 변환."""
    return {
        "code": item.get('pdno'),
        "name": item.get('prdt_name'),
        "qty": int(item.get('hldg_qty', 0)),
        "avg_price": float(item.get('pchs_avg_pric', 0)),   # 매입 평균가
        "current_price": float(item.get('prpr', 0)),        # 현재가
        "profit_rate": float(item.get('evlu_pfls_rt', 0)),  # 수익률
        "pl_amount": int(float(item.get('evlu_pfls_amt', 0) or 0)),  # 평가손익(원)
    }

def get_balance():
    """
    현재 계좌의 잔고 현황과 보유 종목 리스트를 반환합니다.
    [Why] 실시간 매매 알고리즘이 현재 보유량과 매수 여력을 정확히 파악하기 위해 필수적인 함수입니다.
    """
    access_token = get_access_token()
    if not access_token:
        # [Rule 4.2] 인증 실패 시 명확한 오류 로그 남김 및 상위 전달
        return {"error": "KIS API 토큰 발급 실패", "holdings": []}

    load_env()
    # 환경 변수에서 계좌 정보 및 키 정보 로드
    app_key = os.environ.get("KIS_APP_KEY", "").strip().replace("\n", "")
    app_secret = os.environ.get("KIS_APP_SECRET", "").strip().replace("\n", "")
    account_no_full = os.environ.get("KIS_ACCOUNT_NO", "").strip().replace("\n", "")
    is_virtual = os.environ.get("KIS_IS_VIRTUAL", "false").lower() == "true"
    
    # 실전/모의 엔드포인트 구분
    default_url = "https://openapi.koreainvestment.com:9443" if not is_virtual else "https://openapivts.koreainvestment.com:29443"
    base_url = os.environ.get("KIS_BASE_URL", default_url)
    
    if not account_no_full:
        return {"error": "계좌 번호가 설정되지 않았습니다.", "holdings": []}

    # 계좌번호 분석 (8자리 계좌번호 + 2자리 상품코드)
    clean_acc = account_no_full.replace('-', '').replace(' ', '')
    if len(clean_acc) < 10:
        return {"error": f"유효하지 않은 계좌번호 형식: {account_no_full}", "holdings": []}
        
    cano = clean_acc[:8]
    acnt_prdt_cd = clean_acc[8:10]

    # 실전: TTTC8434R, 모의: VTTC8434R (주식 잔고 조회용 TR ID)
    tr_id = "VTTC8434R" if is_virtual else "TTTC8434R"
    url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance"

    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P",
    }
    
    # KIS API 필수 파라미터 (주식 잔고 조회용)
    params = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "AFHR_FLG": "N", # 시간외 단일가 구분
        "OCCN_TX_FOR_YN": "N", # 외국인 거래 여부
        "PRDT_TYPE_CD": "01", # 종목 구분 (01: 주식)
        "INQR_DVSN": "01", # Changed from '02' to '01' (Account-based)
        "UNPR_DVSN": "01", # 단가 구분 (01: 평균단가)
        "FUND_STTL_ICLD_YN": "N", # 펀드 결제 포함 여부
        "FNCG_AMT_AUTO_RDPT_YN": "N", # 융자 금액 자동 상환 여부
        "PRCS_DVSN": "01", # Changed from '00' to '01' (Standard for '01' INQR_DVSN)
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }

    # [Rule 4.4] 문제 발생 시 능동적 해결: 에러 7(조회이후 자료변경) 대응 재시도 로직
    max_retries = 3
    for i in range(max_retries):
        try:
            # 텔레그램 알림 성능을 위해 타임아웃 5초 설정
            res = requests.get(url, headers=headers, params=params, timeout=5)
            if res.status_code != 200:
                if i < max_retries - 1:
                    time.sleep(1 + i)
                    continue
                return {"error": f"HTTP {res.status_code}: {res.text}", "holdings": []}
                
            data = res.json()
            rt_cd = data.get('rt_cd')
            
            # [What] KIS 서버 데이터 갱신 중 호출 시 발생하는 '에러 7' 대응
            if rt_cd == '7' and i < max_retries - 1:
                delay = 1.5 + (i * 1.5)
                print(f"[Balance] ⚠️ '자료변경(7)' 에러 발생. 파라미터 초기화 후 {i+1}차 재시도 중 ({delay}초 대기)...")
                # [Standard] 에러 7 발생 시 연속조회 키를 초기화하고 처음부터 다시 요청해야 함
                params["CTX_AREA_FK100"] = ""
                params["CTX_AREA_NK100"] = ""
                time.sleep(delay)
                continue

            if rt_cd != '0':
                return {"error": f"KIS API 오류: {data.get('msg1')} ({data.get('msg_cd')})", "holdings": []}

            output1 = data.get('output1', []) # 종목 리스트
            output2 = data.get('output2', [{}])[0] # 계좌 요약 (예수금 등)
            
            holdings = []
            for item in output1:
                # 보유 수량이 있는 종목만 필터링
                if int(item.get('hldg_qty', 0)) > 0:
                    holdings.append(_parse_holding(item))
            
            return {
                "deposit": int(output2.get('dnca_tot_amt', 0)), # 예수금
                "total_asset": int(output2.get('tot_evlu_amt', 0)), # 총 평가 자산
                "total_profit": int(output2.get('evlu_pfls_smtl_amt', 0)), # 총 평가 손익
                "holdings": holdings,
                "raw": data
            }
        except Exception as e:
            # 예외 발생 시 재시도 시도
            if i < max_retries - 1:
                time.sleep(1)
                continue
            # Rule 4.2: 예외 트래킹을 위한 상세 정보 제공
            return {"error": f"밸런스 조회 예외: {str(e)}", "holdings": []}

if __name__ == "__main__":
    # 독립 실행 시 결과 확인
    result = get_balance()
    if "error" in result:
        print(f"❌ 오류: {result['error']}")
    else:
        print(f"=== [KIS] 실시간 계좌 요약 ===")
        print(f"총자산: {result['total_asset']:,}원")
        print(f"예수금: {result['deposit']:,}원")
        print(f"보유종목수: {len(result['holdings'])}개")
        for h in result['holdings']:
            print(f"- {h['name']} ({h['code']}): {h['qty']}주 | 수익: {h['profit_rate']}%")
