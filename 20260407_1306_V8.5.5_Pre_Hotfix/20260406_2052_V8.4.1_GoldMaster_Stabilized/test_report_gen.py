import sys
import os
import json

# 프로젝트 루트 경로 추가
root_dir = os.getcwd()
if root_dir not in sys.path:
    sys.path.append(root_dir)

# 모듈 임포트
from src.strategy.advisor import StrategyAdvisor

def test_report_generation():
    print("=== [Test] Strategy Report Generation ===")
    
    # 1. 테스트 데이터 준비 (Naver 증권 등에서 수집된 형식의 모의 데이터)
    mock_data = [
        {
            "name": "삼성전자",
            "code": "005930",
            "price": 75000,
            "change_rate": 1.2,
            "recent_posts_count": 800,
            "positive_rate": 65.0,
            "posts_summary": "반도체 수요 회복 기대감",
            "top_keywords": "반도체, 실적"
        },
        {
            "name": "기가레인",
            "code": "049080",
            "price": 2400,
            "change_rate": 5.5,
            "recent_posts_count": 120,
            "positive_rate": 80.0,
            "posts_summary": "5G 핵심 부품 공급 계약",
            "top_keywords": "5G, 수주"
        }
    ]
    
    try:
        # 2. Advisor 인스턴스 생성
        print("[Test] Advisor 인스턴스 생성 중...")
        advisor = StrategyAdvisor()
        
        # 3. 리포트 생성 호출
        print("[Test] generate_report() 호출 중...")
        report_text, items = advisor.generate_report(mock_data, allow_buy=True)
        
        # 4. 결과 출력
        print("\n=== [Test Result] ===")
        print(report_text)
        print("\n[Item Count]:", len(items))
        print("=== [Test Successful] ===")
        
    except Exception as e:
        print("\n=== [Test FAILED] ===")
        import traceback
        traceback.print_exc()
        print(f"Error Type: {type(e).__name__}")
        print(f"Error Message: {e}")

if __name__ == "__main__":
    test_report_generation()
