import os
import sys

# 경로 설정
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.strategy.simulators.sim1_psych import PsychDivergenceSimulator
from src.strategy.simulators.sim2_spillover import SectorSpilloverSimulator
from src.strategy.simulators.sim3_risk import SmartRiskSimulator

def main():
    print("--- 시뮬레이터 3종 강제 초기화 시작 (예수금 500만 원) ---")
    
    sims = [
        PsychDivergenceSimulator(initial_cash=5000000),
        SectorSpilloverSimulator(initial_cash=5000000),
        SmartRiskSimulator(initial_cash=5000000)
    ]
    
    for sim in sims:
        print(f"[{sim.name}] 리셋 중...")
        sim.reset_state()
        # 리셋 후 즉시 저장 확인
        if os.path.exists(sim.state_file):
            print(f"  - {sim.state_file} 초기화 완료 (현금: {sim.state['cash']:,}원)")
            
    print("\n모든 시뮬레이터가 5,000,000원 클린 상태로 리셋되었습니다.")

if __name__ == "__main__":
    main()
