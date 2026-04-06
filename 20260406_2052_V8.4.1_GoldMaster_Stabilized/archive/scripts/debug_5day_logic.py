
import sys
import os
import pandas as pd
from datetime import datetime
import json

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from analyzer_5days import analyze_cumulative, load_daily_snapshots, get_recent_working_days

def debug_consecutive_days():
    target_code = '005930' # Samsung Electronics

    print(f"\n[Debug] Analyzing 5-day logic for {target_code}...")
    
    # 1. Check Date Calculation
    dates = get_recent_working_days(5)
    print(f"[Debug] Target Dates: {dates}")

    # 2. Check File Loading
    daily_dfs = load_daily_snapshots(dates)
    print(f"[Debug] Loaded Files for {len(daily_dfs)} dates.")
    for d, df in daily_dfs.items():
        print(f"  - {d}: {len(df)} records")
        # Check if target exists
        if 'code' in df.columns:
            # Ensure code is string and zero-padded
            df['code'] = df['code'].astype(str).str.zfill(6)
            row = df[df['code'] == target_code]
            if not row.empty:
                print(f"    -> Found {target_code} in {d}")
            else:
                print(f"    -> NOT FOUND {target_code} in {d}")
        else:
            print(f"    -> 'code' column missing in {d}")

    # 3. Run Analysis
    df_result = analyze_cumulative(5, silent=True)
    if not df_result.empty:
        row = df_result[df_result['code'] == target_code]
        if not row.empty:
            print(f"\n[Result] {target_code} Consecutive Days: {row.iloc[0]['consecutive_days']}")
            print(f"[Result] {target_code} Total Posts: {row.iloc[0]['total_posts']}")
        else:
            print(f"\n[Result] {target_code} not found in result.")
    else:
        print("\n[Result] Result DataFrame is empty.")

if __name__ == "__main__":
    debug_consecutive_days()
