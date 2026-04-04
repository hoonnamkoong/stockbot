
import pandas as pd
import os
import re
import glob
import json
import holidays
from datetime import datetime, timedelta
import statistics

def get_recent_working_days(count=5):
    """
    Returns a list of the last `count` working days (including today), as 'YYYY-MM-DD' strings.
    Excludes weekends and KR holidays.
    """
    kr_holidays = holidays.KR()
    working_days = []
    
    # Start from today (KST)
    # Use UTC to safe add 9 hours regardless of server location
    current_date = datetime.utcnow() + timedelta(hours=9) 
    
    check_date = current_date
    
    while len(working_days) < count:
        date_str = check_date.strftime('%Y-%m-%d')
        is_weekend = check_date.weekday() >= 5
        is_holiday = date_str in kr_holidays
        
        if not is_weekend and not is_holiday:
            working_days.append(date_str)
            
        check_date -= timedelta(days=1)
        
    return working_days

def normalize_columns(df):
    """
    Renames Korean columns to English for consistency.
    """
    col_map = {
        '종목코드': 'code',
        '종목명': 'name',
        '시장구분': 'market',
        '시장': 'market', # Legacy support
        '현재가': 'price',
        '등락률': 'change_rate',
        '당일_게시글수': 'recent_posts_count', 
        '당일 게시글수': 'recent_posts_count',
        '게시글수': 'recent_posts_count', # Legacy
        '현재_외국인비중': 'foreign_rate',
        '외인소진율': 'foreign_rate', # Legacy
        '어제_종가': 'prev_close',
        '어제_외국인비중': 'prev_foreign_rate',
        '연속_등록': 'is_last_captured'
    }
    return df.rename(columns=col_map)

def safe_int(val, default=0):
    try:
        if pd.isna(val): return default
        if isinstance(val, (int, float)): return int(val)
        return int(str(val).replace(',', '').strip())
    except:
        return default

def safe_float(val, default=0.0):
    try:
        if pd.isna(val): return default
        if isinstance(val, (int, float)): return float(val)
        return float(str(val).replace(',', '').replace('%', '').strip())
    except:
        return default

def load_daily_snapshots(target_dates):
    """
    For each target date, find Excel/CSV files by scanning the data/ folder.
    Files are named like: trending_integrated_YYYYMMDD_HHMMSS.xlsx
    Extracts date from filename and picks the latest file per day.
    Returns a dict: { 'YYYY-MM-DD': DataFrame }
    """
    daily_dfs = {}
    data_dir = 'data'
    
    if not os.path.exists(data_dir):
        print(f"[5Day] {data_dir} folder not found.")
        return {}
    
    # Pattern: trending_integrated_YYYYMMDD_HHMMSS.xlsx or .csv
    pattern = re.compile(r'trending_integrated_(\d{8})_(\d{6})\.(xlsx|csv)$')
    
    # Build a map: { 'YYYY-MM-DD': [ (timestamp_str, filepath) ] }
    date_files = {}
    for filename in os.listdir(data_dir):
        match = pattern.match(filename)
        if match:
            date_raw = match.group(1)  # e.g. '20260210'
            time_raw = match.group(2)  # e.g. '022419'
            ext = match.group(3)
            try:
                file_date = datetime.strptime(date_raw, '%Y%m%d').strftime('%Y-%m-%d')
            except ValueError:
                continue
            
            filepath = os.path.join(data_dir, filename)
            if file_date not in date_files:
                date_files[file_date] = []
            # Prefer xlsx over csv; use time as tiebreaker
            date_files[file_date].append((time_raw, ext, filepath))
    
    print(f"[5Day] Found files for {len(date_files)} dates: {sorted(date_files.keys())}")
    
    for date_str in target_dates:
        if date_str not in date_files:
            print(f"[5Day] No file found for {date_str}")
            continue
        
        # Sort: prefer xlsx over csv, then latest time
        candidates = date_files[date_str]
        # Sort by (extension priority: xlsx=0, csv=1), then by time descending
        candidates.sort(key=lambda x: (0 if x[1] == 'xlsx' else 1, x[0]), reverse=False)
        # After sort, xlsx comes first; among xlsx, earliest time is first
        # We want latest time with xlsx preference
        candidates.sort(key=lambda x: (0 if x[1] == 'xlsx' else 1, -int(x[0]) if x[0].isdigit() else 0))
        
        best = candidates[0]
        file_path = best[2]
        
        try:
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
            elif file_path.endswith('.xlsx'):
                df = pd.read_excel(file_path)
            else:
                continue
            
            df = normalize_columns(df)
            daily_dfs[date_str] = df
            print(f"[5Day] Loaded {date_str}: {len(df)} stocks from {os.path.basename(file_path)}")
        except Exception as e:
            print(f"[5Day] Error loading {file_path}: {e}")
    
    return daily_dfs

def analyze_cumulative(days=5, silent=False):
    if not silent:
        print(f"\n[{days}Day Analysis] Starting V3 (Robust)...")
    
    target_dates = get_recent_working_days(days) 
    if not silent:
        print(f"[{days}Day Analysis] Target Dates: {target_dates}")
    
    daily_dfs = load_daily_snapshots(target_dates) 
    if not daily_dfs:
        if not silent:
            print(f"[{days}Day Analysis] No data found.")
        return pd.DataFrame()

    all_codes = set()
    for date_str, df in daily_dfs.items():
        if 'code' in df.columns:
            df['code'] = df['code'].astype(str).str.zfill(6)
            all_codes.update(df['code'].tolist())
            
    if not all_codes:
        if not silent:
            print(f"[{days}Day Analysis] No stock codes found in loaded data.")
        return pd.DataFrame()
        
    records = []
    
    if not silent:
        print(f"[{days}Day Analysis] Found {len(all_codes)} unique codes across {days} days.")

    for code in all_codes:
        consecutive_days = 0  # Total appearance count across the period
        
        total_posts = 0
        posts_list = []
        change_rates = []
        prices = []
        
        latest_meta = {}
        
        for i, date_str in enumerate(target_dates):
            df = daily_dfs.get(date_str)
            found_row = False
            
            if df is not None and not df.empty and 'code' in df.columns:
                row = df[df['code'] == code]
                if not row.empty:
                    found_row = True
                    data = row.iloc[0]
                    
                    if not latest_meta:
                        latest_meta = {
                            'name': data.get('name', ''),
                            'market': data.get('market', ''),
                            'price': data.get('price', 0),
                            'change_rate': data.get('change_rate', '0%'),
                            'prev_close': data.get('prev_close', 0),
                            'code': code
                        }
                    
                    consecutive_days += 1
                        
                    p_count = safe_int(data.get('recent_posts_count'))
                    total_posts += p_count
                    posts_list.append(p_count)
                    
                    c_rate = safe_float(data.get('change_rate'))
                    change_rates.append(c_rate)
                        
                    p_price = safe_int(data.get('price')) 
                    prices.append(p_price)
                        
            if not found_row:
                # Interpolation: use last known values if available, or latest_meta
                prev_p = prices[-1] if prices else (safe_int(latest_meta.get('price')) if latest_meta else 0)
                prices.append(prev_p)
                posts_list.append(0) # Posts should still be 0 if not featured
                change_rates.append(0.0)
        
        if not latest_meta:
            continue
            
        avg_posts = total_posts / days 
        if len(posts_list) > 1:
            std_dev = statistics.stdev(posts_list)
        else:
            std_dev = 0
            
        # Filter out 0s for stats
        valid_prices = [p for p in prices if p > 0]
        price_start = valid_prices[-1] if valid_prices else 0
        
        # Calculate period change using OLDEST VALID price
        period_change = 0
        if valid_prices:
             period_change = round((safe_int(latest_meta.get('price')) - valid_prices[-1]) / valid_prices[-1] * 100, 2)

        record = {
            'code': code,
            'name': latest_meta.get('name'),
            'market': latest_meta.get('market'),
            'price': safe_int(latest_meta.get('price')),
            'change_rate': latest_meta.get('change_rate'),
            'period_change_rate': period_change,
            'daily_change_rate': safe_float(latest_meta.get('change_rate')), # Use raw scraper value or calc? Scraper is usually correct for daily.
            # However, user requested "relative to prev_close". Scraper's change_rate is usually (price - prev_close)/prev_close.
            # Let's ensure we pass what the scraper found.
            'prev_close': safe_int(latest_meta.get('prev_close')), 
            'consecutive_days': consecutive_days,
            'total_posts': total_posts,
            'avg_posts': round(avg_posts, 1),
            'std_dev': round(std_dev, 1),
            'price_start': price_start,
            # Price Trend (Value)
            'sparkline_price': prices[::-1], # Oldest to Newest (may contain 0s)
            'price_stats': {
                 'min': min(valid_prices) if valid_prices else 0,
                 'max': max(valid_prices) if valid_prices else 0,
                 'avg': int(sum(valid_prices)/len(valid_prices)) if valid_prices else 0
            },
            # Post Trend (Value)
            'sparkline_posts': posts_list[::-1], # Oldest to Newest
            'post_stats': {
                'min': min(posts_list) if posts_list else 0,
                'max': max(posts_list) if posts_list else 0,
                'avg': round(sum(posts_list)/len(posts_list), 1) if posts_list else 0
            }
        }
        records.append(record)
        
    result_df = pd.DataFrame(records)
    
    if not result_df.empty:
        result_df = result_df.sort_values(by=['consecutive_days', 'total_posts'], ascending=[False, False])
        
    if not silent:
        print(f"[{days}Day Analysis] Generated {len(result_df)} records.")
        
    # [Fix 2026-01-13] Ensure no NaNs in output
    # [Fix 2026-02-10] Ensure no NaNs in output (Strict sanitization)
    result_df = result_df.fillna(0) # Simple fillna(0) for numeric safety
    result_df = result_df.replace({float('nan'): 0, float('inf'): 0, -float('inf'): 0})
    return result_df

def analyze_5days():
    return analyze_cumulative(5)

def analyze_3days():
    return analyze_cumulative(3)

import sys
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=5, help='Number of days to analyze')
    parser.add_argument('--json', action='store_true', help='Output result as JSON')
    args = parser.parse_args()

    # Force stdout to UTF-8 to prevent mojibake in Node.js spawn
    if args.json:
        sys.stdout.reconfigure(encoding='utf-8')

    df = analyze_cumulative(args.days, silent=args.json)

    if args.json:
        # Output strictly JSON for API consumption
        if df.empty:
            print("[]")
        else:
            print(df.to_json(orient='records', force_ascii=False))
    else:
        # Normal console output
        if not df.empty:
            pd.set_option('display.max_columns', None)
            pd.set_option('display.width', 1000)
            print(df.head())
