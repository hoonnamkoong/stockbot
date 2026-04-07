import os
import sys
import json
import datetime
import requests
from bs4 import BeautifulSoup

# 경로 설정
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.strategy.simulators.original_simulator import OriginalSimulator
from src.strategy.simulators.aggressive_simulator import AggressiveSimulator
from src.strategy.simulators.conviction_simulator import ConvictionSimulator
from src.strategy.simulators.base_simulator import BaseSimulator

def get_current_price(code):
    """네이버 금융에서 실시간 현재가 추출"""
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.content, 'html.parser')
        price_tag = soup.select_one('.no_today .blind')
        if price_tag:
            return int(price_tag.text.replace(',', ''))
    except: pass
    return None

def get_all_simulation_stats():
    """
    [V8.6.2 Tripod Sync] 
    - 3개 시뮬레이터 인스턴스 생성 및 상태 로드
    - 보유 종목 현재가 일괄 업데이트 및 NAV 산출
    """
    sims = {
        "sim1": OriginalSimulator(),
        "sim2": AggressiveSimulator(),
        "sim3": ConvictionSimulator(),
        "real": BaseSimulator("Real")
    }
    
    # 모든 종목의 현재가 수집 리스트
    all_codes = set()
    for s in sims.values():
        all_codes.update(s.state.get('portfolio', {}).keys())
    
    # 실시간 가격 맵핑
    price_map = {}
    for code in all_codes:
        price = get_current_price(code)
        if price: price_map[code] = price
        
    # 결과 취합
    results = {}
    for key, sim in sims.items():
        results[key] = sim.get_normalized_stats(current_prices=price_map)
        
    results["last_updated"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return results

if __name__ == "__main__":
    stats = get_all_simulation_stats()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
