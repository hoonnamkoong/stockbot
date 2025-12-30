
import pandas as pd
import os
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
    current_date = datetime.now() + timedelta(hours=9) 
    
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
        '종목명': 'name',
        '시장구분': 'market',
        '현재가': 'price',
        '등락률': 'change_rate',
        '당일_게시글수': 'recent_posts_count', # Also handle variants
        '당일 게시글수': 'recent_posts_count',
        '게시글수': 'recent_posts_count',
        '현재_외국인비중': 'foreign_rate',
        '어제_종가': 'prev_close'
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
    For each target date, find the LAST generated report file from reports.json.
    Returns a dict: { 'YYYY-MM-DD': DataFrame }
    """
    daily_dfs = {}
    reports_file = 'data/reports.json'
    
    if not os.path.exists(reports_file):
        print(f"[5Day] {reports_file} not found.")
        return {}
        
    try:
        with open(reports_file, 'r', encoding='utf-8') as f:
            reports = json.load(f)
            
        for date_str in target_dates:
            # Filter reports for this date
            day_reports = [r for r in reports if r['date'].startswith(date_str)]
            
            if not day_reports:
                continue
                
            # Take the first one (assuming sorted desc by timestamp in updates)
            # If not sorted, we might need to sort by timestamp
            day_reports.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
            last_report = day_reports[0]
            
            filename = last_report['filename']
            # Search logic
            possible_paths = [
                filename,
                f"data/{filename}",
                os.path.join(os.getcwd(), 'data', filename),
                os.path.join(os.getcwd(), filename)
            ]
            
            file_path = None
            for p in possible_paths:
                if os.path.exists(p):
                    file_path = p
                    break
            
            if file_path:
                try:
                    if file_path.endswith('.csv'):
                        df = pd.read_csv(file_path)
                    elif file_path.endswith('.xlsx'):
                        df = pd.read_excel(file_path)
                    else:
                        continue
                    
                    df = normalize_columns(df)
                    # Debug print
                    # print(f"[5Day] Loaded {date_str} cols: {list(df.columns)}")
                    
                    daily_dfs[date_str] = df
                except Exception as e:
                    print(f"[5Day] Error loading {filename}: {e}")
            else:
                print(f"[5Day] File not found: {filename}")
                    
    except Exception as e:
        print(f"[5Day] Error reading reports.json: {e}")
        
    return daily_dfs

def analyze_5days():
    print("\n[5Day Analysis] Starting V3 (Robust)...")
    
    target_dates = get_recent_working_days(5) 
    print(f"[5Day Analysis] Target Dates: {target_dates}")
    
    daily_dfs = load_daily_snapshots(target_dates) 
    if not daily_dfs:
        print("[5Day Analysis] No data found.")
        return pd.DataFrame()

    all_codes = set()
    for date_str, df in daily_dfs.items():
        if 'code' in df.columns:
            df['code'] = df['code'].astype(str).str.zfill(6)
            all_codes.update(df['code'].tolist())
            
    if not all_codes:
        print("[5Day Analysis] No stock codes found in loaded data.")
        return pd.DataFrame()
        
    records = []
    
    # debug count
    print(f"[5Day Analysis] Found {len(all_codes)} unique codes across 5 days.")

    for code in all_codes:
        consecutive_days = 0 
        is_consecutive_broken = False
        
        total_posts = 0
        posts_list = []
        change_rates = []
        prices = []
        
        latest_meta = {}
        
        for i, date_str in enumerate(target_dates):
            df = daily_dfs.get(date_str)
            
            # Use found_row to verify presence
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
                            'code': code
                        }
                    
                    if not is_consecutive_broken:
                        consecutive_days += 1
                        
                    p_count = safe_int(data.get('recent_posts_count'))
                    total_posts += p_count
                    posts_list.append(p_count)
                    
                    c_rate = safe_float(data.get('change_rate'))
                    change_rates.append(c_rate)
                        
                    p_price = safe_int(data.get('price')) # Price is usually int in KRW
                    prices.append(p_price)
                        
            if not found_row:
                if not is_consecutive_broken:
                    is_consecutive_broken = True
                posts_list.append(0)
                change_rates.append(0.0)
        
        if not latest_meta:
            continue
            
        avg_posts = total_posts / 5 
        if len(posts_list) > 1:
            std_dev = statistics.stdev(posts_list)
        else:
            std_dev = 0
            
        record = {
            'code': code,
            'name': latest_meta.get('name'),
            'market': latest_meta.get('market'),
            'price': safe_int(latest_meta.get('price')), # Clean numeric
            'change_rate': latest_meta.get('change_rate'), # String is fine format
            'consecutive_days': consecutive_days,
            'total_posts': total_posts,
            'avg_posts': round(avg_posts, 1),
            'std_dev': round(std_dev, 1),
            'sparkline': change_rates[::-1],
            'price_start': prices[-1] if prices else 0, # Price from 5 days ago (or oldest in window)
            'trend_stats': {
                'min': round(min(change_rates), 2) if change_rates else 0,
                'max': round(max(change_rates), 2) if change_rates else 0,
                'avg': round(sum(change_rates)/len(change_rates), 2) if change_rates else 0
            }
        }
        records.append(record)
        
    result_df = pd.DataFrame(records)
    
    if not result_df.empty:
        result_df = result_df.sort_values(by=['consecutive_days', 'total_posts'], ascending=[False, False])
        
    print(f"[5Day Analysis] Generated {len(result_df)} records.")
    return result_df

if __name__ == "__main__":
    df = analyze_5days()
    if not df.empty:
        print(df.head())
        # print(df.iloc[0].to_dict())
