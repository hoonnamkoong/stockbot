import os
import sys
import json

# 프로젝트 루트 경로 추가
sys.path.append(os.path.join(os.getcwd(), 'src'))

from strategy.simulators.sim1_original import OriginalSimulator
from strategy.simulators.sim2_conservative import ConservativeSimulator
from strategy.simulators.sim3_aggressive import AggressiveSimulator

def force_update_stats():
    sims = [
        OriginalSimulator(),
        ConservativeSimulator(),
        AggressiveSimulator()
    ]
    
    for sim in sims:
        print(f"Updating stats for {sim.name}...")
        # 기존 저장된 상태를 로드
        sim.load_state()
        # save_state()를 호출하면 새로운 로직에 의해 raw_stats와 normalized_stats가 저장됨
        sim.save_state()
        print(f"Stats for {sim.name} updated.")

if __name__ == "__main__":
    force_update_stats()
