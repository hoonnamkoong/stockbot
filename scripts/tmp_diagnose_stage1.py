import sys
import os
from datetime import datetime, timedelta

# 경로 설정
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from strategy import analyzer

def get_current_kst_time():
    return datetime.utcnow() + timedelta(hours=9)

def get_threshold_by_time(hour):
    if 0 <= hour < 9: return 20
    elif 9 <= hour < 11: return 40
    elif 11 <= hour < 14: return 80
    elif 14 <= hour < 16: return 120
    return 130

def test_stage_1():
    now_kst = get_current_kst_time()
    threshold = get_threshold_by_time(now_kst.hour)
    print(f"Current KST: {now_kst}, Threshold: {threshold}")
    
    try:
        kospi = analyzer.get_top_trending_stocks('KOSPI')
        kosdaq = analyzer.get_top_trending_stocks('KOSDAQ')
        candidates = kospi + kosdaq
        print(f"Total candidates from Naver: {len(candidates)}")
        
        # scraper.py의 get_discussion_stats 로직을 간략화하여 확인
        import requests
        from bs4 import BeautifulSoup
        import re
        
        results = []
        for s in candidates[:10]: # 시간 관계상 상위 10개만 테스트
            code = s['code']
            url = f"https://finance.naver.com/item/board.naver?code={code}"
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(res.content, 'html.parser')
            # 게시글 개수 파악 (단순화)
            # 실제 scraper.py는 누적 카운트를 사용하므로, 여기서는 페이지당 개수로 추정하거나 
            # 단순히 1페이지 개수가 몇 개인지 확인
            rows = soup.select('table.type2 tr')
            post_count = len([r for r in rows if r.select_one('td.title')])
            print(f"Stock: {s['name']} ({code}), Posts in Page 1: {post_count}")
            
            # 실제 scraper.py에서는 prev_state와 비교하여 9페이지까지 뒤집니다.
            # 여기서는 API 호출 안정성만 확인
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_stage_1()
