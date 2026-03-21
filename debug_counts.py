
import os
import sys
from datetime import datetime, timedelta
import pandas as pd
import re

# Add root to path to import from scraper if possible, or just copy-paste the function
def calculate_long_term_consecutive_days(current_codes):
    consecutive_counts = {code: 1 for code in current_codes} # Default 1 (today)
    active_codes = set(current_codes)
    
    data_dir = 'data'
    if not os.path.exists(data_dir):
        return consecutive_counts
    
    pattern = re.compile(r'trending_integrated_(\d{8})_(\d{6})\.(xlsx|csv)$')
    date_files = {} 
    
    for filename in os.listdir(data_dir):
        match = pattern.match(filename)
        if match:
            d_str = match.group(1) # YYYYMMDD
            t_str = match.group(2) # HHMMSS
            try:
                date_obj = datetime.strptime(d_str, '%Y%m%d')
                date_fmt = date_obj.strftime('%Y-%m-%d')
                if date_fmt not in date_files:
                    date_files[date_fmt] = []
                date_files[date_fmt].append((t_str, os.path.join(data_dir, filename)))
            except:
                continue
            
    sorted_dates = sorted(date_files.keys(), reverse=True)
    
    # Simulate today as the most recent file date or actual today
    # Let's see what's the latest date in the folder
    if not sorted_dates:
        return consecutive_counts
    
    latest_date = sorted_dates[0]
    print(f"Latest date in folder: {latest_date}")
    print(f"Total dates found: {len(sorted_dates)}")
    
    for d_str in sorted_dates:
        if d_str == latest_date:
            continue
        
        if not active_codes:
            break 
        
        files = sorted(date_files[d_str], key=lambda x: x[0], reverse=True)
        best_time, filepath = files[0] 
        
        try:
            if filepath.endswith('.csv'):
                try:
                    df = pd.read_csv(filepath, dtype=str)
                except:
                    df = pd.read_csv(filepath, dtype=str, encoding='cp949')
            else:
                df = pd.read_excel(filepath, dtype=str)
            
            day_codes = set()
            target_cols = ['종목코드', 'Code', 'code', 'Symbol', 'symbol']
            found_col = None
            for col in target_cols:
                if col in df.columns:
                    found_col = col
                    break
            
            if found_col:
                day_codes = set(df[found_col].astype(str).str.replace('A', '').str.zfill(6).tolist())
            else:
                first_col = df.columns[0]
                day_codes = set(df[first_col].astype(str).str.zfill(6).tolist())

            next_active = set()
            for code in active_codes:
                if code in day_codes:
                    consecutive_counts[code] += 1
                    next_active.add(code)
            
            # If a gap occurs, those codes stop incrementing
            # (Wait, actually active_codes = next_active ensures that once a code is missing, it's GONE)
            active_codes = next_active
            print(f"Date: {d_str}, File: {os.path.basename(filepath)}, Active stocks remaining: {len(active_codes)}")
            
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
            continue

    return consecutive_counts

if __name__ == "__main__":
    # Test with Samsung Electronics (005930) and some others
    test_codes = ['005930', '000660', '035420']
    counts = calculate_long_term_consecutive_days(test_codes)
    print("\nConsecutive Days Result:")
    for code, count in counts.items():
        print(f"Code {code}: {count} days")
