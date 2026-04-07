import os
import sys
import json

# 경로 설정
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.strategy.simulators.sim1_original import OriginalSimulator
from src.strategy.simulators.sim2_aggressive import AggressiveSimulator
from src.strategy.simulators.sim3_conviction import ConvictionSimulator
from src.strategy.simulators.base_simulator import BaseSimulator

def get_all_simulation_stats():
    """
    [Tripod Sync] 3개 채널의 시뮬레이터 통계를 통합하여 반환
    """
    # 1. 시뮬레이터 인스턴스 생성
    sim1 = OriginalSimulator()
    sim2 = AggressiveSimulator()
    sim3 = ConvictionSimulator()
    
    # 2. 실전 계좌 (Sim 0) - BaseSimulator를 활용해 로그 기반으로 산출
    # 데이터 폴더에 sim_real_state.json 등이 있다고 가정
    sim_real = BaseSimulator("Real")
    
    return {
        "real": sim_real.get_normalized_stats(),
        "sim1": sim1.get_normalized_stats(),
        "sim2": sim2.get_normalized_stats(),
        "sim3": sim3.get_normalized_stats(),
        "last_updated": json.loads(json.dumps(datetime.datetime.now(), default=str))
    }

if __name__ == "__main__":
    import datetime
    stats = get_all_simulation_stats()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
