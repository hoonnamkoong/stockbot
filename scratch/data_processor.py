import pandas as pd
import os
import json
import glob

def integrate_excel_files():
    files = [
        'data/trending_integrated_2026-01.xlsx',
        'data/trending_integrated_2026-02.xlsx',
        'data/trending_integrated_2026-03.xlsx',
        'data/trending_integrated_2026-04.xlsx'
    ]
    
    all_df = []
    for f in files:
        if os.path.exists(f):
            print(f"Reading {f}...")
            # Using try-except for potential encoding issues or missing files
            try:
                df = pd.read_excel(f)
                all_df.append(df)
            except Exception as e:
                print(f"Error reading {f}: {e}")
    
    if all_df:
        integrated_df = pd.concat(all_df, ignore_index=True)
        output_path = 'data/integrated_2026_Q1_Q4.csv'
        integrated_df.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"Integrated database saved to {output_path}")
        return len(integrated_df)
    return 0

def analyze_sim_history():
    tracks = ['original', 'aggressive', 'conservative']
    summaries = {}
    
    for track in tracks:
        file_path = f'data/trade_history_sim_{track}.csv'
        if os.path.exists(file_path):
            df = pd.read_csv(file_path)
            # Assuming columns: timestamp, symbol, side (buy/sell), price, quantity, total_amount, reason
            # Let's try to infer profit if possible, or just summary stats
            
            total_trades = len(df)
            buy_trades = len(df[df['side'] == 'buy']) if 'side' in df.columns else 0
            sell_trades = len(df[df['side'] == 'sell']) if 'side' in df.columns else 0
            
            # Simple stats
            summaries[track] = {
                "total_records": total_trades,
                "buy_count": buy_trades,
                "sell_count": sell_trades,
                "reasons": df['reason'].value_counts().to_dict() if 'reason' in df.columns else {},
                "symbols": df['symbol'].value_counts().head(10).to_dict() if 'symbol' in df.columns else {}
            }
            
            # If we have price and quantity, we could calculate ROI, but let's stick to what we have.
            # In some versions, 'profit' might be recorded. Let's check columns.
            if 'profit' in df.columns:
                summaries[track]['total_profit'] = df['profit'].sum()
                summaries[track]['avg_profit'] = df['profit'].mean()
        else:
            summaries[track] = "File not found"
            
    return summaries

if __name__ == "__main__":
    count = integrate_excel_files()
    sim_stats = analyze_sim_history()
    
    result = {
        "integrated_records": count,
        "simulation_analysis": sim_stats
    }
    
    with open('scratch/summary_for_debate.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print("Data processing complete. Summary saved to scratch/summary_for_debate.json")
