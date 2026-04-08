import os
import json
import shutil
from datetime import datetime

def reset_simulators():
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
        print(f"[Reset] Created data directory: {data_dir}")

    sim_types = ['original', 'aggressive', 'conviction']
    initial_cash = 3000000
    
    # 1. 상태 파일 리셋
    for sim in sim_types:
        state_file = os.path.join(data_dir, f"sim_{sim}_state.json")
        log_file = os.path.join(data_dir, f"sim_{sim}_log.json")
        csv_file = os.path.join(data_dir, f"trade_history_sim_{sim}.csv")
        
        # 새 상태 데이터
        new_state = {
            "initial_cash": initial_cash,
            "cash": initial_cash,
            "invested": 0,
            "portfolio": {},
            "peak_nav": initial_cash,
            "history": [initial_cash],
            "daily_trades": []
        }
        
        # 파일 쓰기
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(new_state, f, ensure_ascii=False, indent=2)
        print(f"[Reset] {sim.capitalize()} state reset to {initial_cash:,} KRW")
        
        # 로그 파일 초기화 (빈 리스트)
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        print(f"[Reset] {sim.capitalize()} log cleared")
        
        # CSV 파일 삭제
        if os.path.exists(csv_file):
            os.remove(csv_file)
            print(f"[Reset] {sim.capitalize()} CSV history deleted")

    print("\n[Success] All simulators have been reset for a fresh start.")

if __name__ == "__main__":
    reset_simulators()
