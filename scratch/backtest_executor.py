import os
import sys
import pandas as pd
import json
from datetime import datetime
import collections

# 경로 설정
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.strategy.simulators.sim1_psych import PsychDivergenceSimulator
from src.strategy.simulators.sim2_spillover import SectorSpilloverSimulator
from src.strategy.simulators.sim3_risk import SmartRiskSimulator
from src.analyzer_5days import normalize_columns

class BacktestSimulator:
    def __init__(self, sim_class, name):
        self.sim = sim_class(initial_cash=3000000)
        self.sim.name = f"BT_{name}"
        self.sim.state_file = os.path.join(_REPO_ROOT, 'data', f"temp_bt_{name}_state.json")
        self.sim.log_file = os.path.join(_REPO_ROOT, 'data', f"temp_bt_{name}_log.json")
        self.sim.csv_file = os.path.join(_REPO_ROOT, 'data', f"temp_bt_{name}_history.csv")
        self.sim.reset_state()

    def run(self, data, prices, market_healthy=True):
        self.sim.state['market_index_healthy'] = market_healthy
        return self.sim.run(data, current_prices=prices)

def main():
    print("--- 1~4월 데이터 기반 V2 통합 백테스트 시작 ---")
    data_dir = os.path.join(_REPO_ROOT, 'data')
    files = sorted([f for f in os.listdir(data_dir) if f.startswith('trending_integrated_2026') and f.endswith('.xlsx')])
    
    sims = {
        "심리 폭발형(V2)": BacktestSimulator(PsychDivergenceSimulator, "Psych"),
        "섹터 전이형(V2)": BacktestSimulator(SectorSpilloverSimulator, "Spillover"),
        "스마트 리스크(V2)": BacktestSimulator(SmartRiskSimulator, "Risk")
    }

    price_history = collections.defaultdict(list)
    buzz_history = collections.defaultdict(list)
    market_nav_history = []

    for i, filename in enumerate(files):
        filepath = os.path.join(data_dir, filename)
        try:
            df = pd.read_excel(filepath)
            df = normalize_columns(df)
            df['code'] = df['code'].astype(str).str.zfill(6)
            
            # 지수 건전성 판단 (단순화: 전체 종목 평균가 추세)
            current_market_avg = df['price'].mean() if 'price' in df.columns else 0
            market_healthy = True
            if market_nav_history and current_market_avg > 0:
                if current_market_avg < market_nav_history[-1] * 0.985: # 1.5% 이상 급락 시
                    market_healthy = False
            market_nav_history.append(current_market_avg)

            processed_data = []
            for _, row in df.iterrows():
                code = row['code']
                price = float(row.get('price', 0))
                buzz = float(row.get('recent_posts_count', 0))
                volume = float(str(row.get('volume', 0)).replace(',', '')) if row.get('volume') else 1_000_000 # 기본값
                
                price_history[code].append(price)
                buzz_history[code].append(buzz)
                
                row_dict = row.to_dict()
                row_dict['price'] = price
                row_dict['volume'] = volume
                
                # 5일 누적 수익률
                if len(price_history[code]) >= 2:
                    start_p = price_history[code][0] if len(price_history[code]) < 5 else price_history[code][-5]
                    row_dict['period_change_rate'] = ((price - start_p) / start_p * 100) if start_p > 0 else 0
                else:
                    row_dict['period_change_rate'] = 0
                
                row_dict['avg_posts'] = sum(buzz_history[code]) / len(buzz_history[code])
                row_dict['sparkline_price'] = price_history[code][-5:]
                processed_data.append(row_dict)
            
            price_map = {row['code']: row['price'] for row in processed_data}
            
            for name, bt_sim in sims.items():
                bt_sim.run(processed_data, price_map, market_healthy=market_healthy)
            
            if i % 10 == 0:
                print(f"진행 중... ({i}/{len(files)}) - {filename} (Market: {'OK' if market_healthy else 'CRASH'})")
        except Exception as e:
            print(f"파일 처리 오류 ({filename}): {e}")

    print("\n--- V2 백테스트 최종 결과 ---")
    results = []
    for name, bt_sim in sims.items():
        stats = bt_sim.sim.calculate_stats()
        results.append({
            "전략": name,
            "최종자산": f"{stats['total_asset']:,.0f}원",
            "수익률": f"{stats['profit_rate']:.2f}%",
            "승률": f"{stats['win_rate']:.1f}%",
            "MDD": f"{stats['mdd']:.2f}%",
            "보유종목": stats['holdings_count']
        })
    print(pd.DataFrame(results).to_string(index=False))

    for bt_sim in sims.values():
        for f in [bt_sim.sim.state_file, bt_sim.sim.log_file, bt_sim.sim.csv_file]:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()
