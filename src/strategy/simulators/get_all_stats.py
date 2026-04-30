import os
import sys
import json
import datetime
import requests
from bs4 import BeautifulSoup

# 경로 설정
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# 신규 시뮬레이터 클래스 임포트
from src.strategy.simulators.sim1_psych import PsychDivergenceSimulator
from src.strategy.simulators.sim2_spillover import SectorSpilloverSimulator
from src.strategy.simulators.sim3_risk import SmartRiskSimulator

def get_market_health():
    """네이버 금융에서 코스피/코스닥 지수를 확인하여 시장 건전성 판단"""
    url = "https://finance.naver.com/sise/sise_index.naver?code=KOSPI"
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.content, 'html.parser')
        
        # 등락 부호 확인 (상승/보합 = True, 하락 = False)
        # 단순히 현재 지수가 전일비 플러스인지 확인 (실전에서는 5일 이평선 등 더 정밀하게 가능)
        change_tag = soup.select_one("#quotation_info .now_value")
        diff_tag = soup.select_one("#quotation_info .rate_info .n_red") # 빨간색(상승)이 있으면 Healthy
        
        if diff_tag: return True
        return False # 파란색(하락)이거나 보합이면 보수적으로 False
    except:
        return True # 오류 시에는 기본적으로 매매 허용

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

def run_all_simulators(data_list):
    """
    [V8.9.9.5] 수석 아키텍트 지침에 따른 모듈형 통합 실행 엔진
    - 3개 시뮬레이터를 딕셔너리로 관리하고 루프를 돌려 일괄 실행
    """
    # 3M 초기화가 보장된 인스턴스 생성
    simulators = {
        "sim1_Psych": PsychDivergenceSimulator(initial_cash=3000000),
        "sim2_Spillover": SectorSpilloverSimulator(initial_cash=3000000),
        "sim3_Risk": SmartRiskSimulator(initial_cash=3000000)
    }
    
    results = {}
    market_healthy = get_market_health()
    print(f"\n[Simulator] {len(simulators)}개 알고리즘 동시 가동 시작... (시장 상태: {'Healthy' if market_healthy else 'Bad'})")
    
    for sim_name, simulator in simulators.items():
        try:
            # 시장 상태 주입
            simulator.state['market_index_healthy'] = market_healthy
            # 모든 시뮬레이터는 동일한 run() 인터페이스를 가짐
            stats = simulator.run(data_list)
            results[sim_name] = stats
            print(f"  - {sim_name} 실행 완료: 승률 {stats.get('win_rate', 0):.1f}% | 자산 {stats.get('total_asset', 0):,.0f}원")
        except Exception as e:
            print(f"  - [Error] {sim_name} 실행 중 오류 발생: {e}")
            results[sim_name] = {"error": str(e)}
            
    return results

def get_all_simulation_stats():
    """
    통합 통계를 위한 래퍼 함수 (호환성 유지)
    """
    # 이 함수는 단순히 현재 상태를 조회할 때 사용 (run() 없이)
    sims = {
        "sim1": PsychDivergenceSimulator(),
        "sim2": SectorSpilloverSimulator(),
        "sim3": SmartRiskSimulator()
    }
    
    all_codes = set()
    for s in sims.values():
        all_codes.update(s.state.get('portfolio', {}).keys())
    
    price_map = {}
    for code in all_codes:
        price = get_current_price(code)
        if price: price_map[code] = price
        
    results = {}
    for key, sim in sims.items():
        results[key] = sim.get_normalized_stats(current_prices=price_map)
        
    # Vercel 대시보드 호환성을 위해 키 값 통일 (sim1, sim2, sim3)
    results["last_updated"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return results

if __name__ == "__main__":
    # 테스트용 가짜 데이터 리스트 (실제 scraper.py 연동 시 data_list를 넘겨야 함)
    # python -m src.strategy.simulators.get_all_stats 등으로 테스트
    print("[get_all_stats] CLI 직접 호출 테스트 (상태 조회)")
    stats = get_all_simulation_stats()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
