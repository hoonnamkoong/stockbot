import json
import os
import sys

# 경로 추가
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

from src.strategy.simulators.original_simulator import OriginalSimulator
from src.strategy.simulators.conviction_simulator import ConvictionSimulator
from src.strategy.simulators.aggressive_simulator import AggressiveSimulator
from src.strategy.simulators.base_simulator import BaseSimulator

def get_all_simulation_stats():
    # 1. 시뮬레이터 인스턴스 생성
    sim1 = OriginalSimulator()
    sim2 = ConvictionSimulator()
    sim3 = AggressiveSimulator()
    
    # 2. 실전 계좌 (Sim 0) - BaseSimulator를 활용해 로그 기반으로 산출
    # 실제 계좌의 매매 로그가 data/sim_real_log.json에 기록된다고 가정
    sim0 = BaseSimulator("Real") 
    
    # 3. 데이터 취합
    all_stats = {
        "Real": sim0.get_normalized_stats(),
        "Sim1": sim1.get_normalized_stats(),
        "Sim2": sim2.get_normalized_stats(),
        "Sim3": sim3.get_normalized_stats()
    }
    
    return all_stats

if __name__ == "__main__":
    stats = get_all_simulation_stats()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
