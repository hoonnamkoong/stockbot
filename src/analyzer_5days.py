import pandas as pd
import os
import json
import holidays
from datetime import datetime, timedelta

def get_recent_working_days(count=5):
    """
    Returns a list of the last `count` working days (including today), as 'YYYY-MM-DD' strings.
    Excludes weekends and KR holidays.
    """
    kr_holidays = holidays.KR()
    working_days = []
    
    # Start from today (KST)
    # Assuming system time is already adjusted or we use scraper's common logic.
    # Here we use datetime.now() assuming it runs in the same environment as scraper.
    # scraper.py sets KST logic via get_current_kst_time(). 
    # To be safe, we'll rely on local time if this runs on the same machine/scheduler.
    
    current_date = datetime.now() + timedelta(hours=9) # Simple KST conversion from UTC if env is UTC
    # Ideally should pass 'now' from scraper, but standalone function is safer.
    
    # If run via scraper, it might be UTC env. 
    # Let's align with scraper.py's get_current_kst_time logic if possible, 
    # but for simplicity, we assume the caller or system time is reasonably managed.
    # We will iterate backwards.
    
    check_date = current_date
    
    while len(working_days) < count:
        date_str = check_date.strftime('%Y-%m-%d')
        is_weekend = check_date.weekday() >= 5
        is_holiday = date_str in kr_holidays
        
        if not is_weekend and not is_holiday:
            working_days.append(date_str)
            
        check_date -= timedelta(days=1)
        
    return working_days # [Today, Yesterday, ...]

def load_daily_snapshots(target_dates):
    """
    For each target date, find the LAST generated report file from reports.json.
    Returns a dict: { 'YYYY-MM-DD': DataFrame }
    """
    daily_dfs = {}
    reports_file = 'data/reports.json'
    
    if not os.path.exists(reports_file):
        return {}
        
    try:
        with open(reports_file, 'r', encoding='utf-8') as f:
            reports = json.load(f)
            
        # reports is a list of entries, sorted desceding by timestamp (usually).
        # We need to find the latest file for each target_date.
        
        for date_str in target_dates:
            # Filter reports for this date
            # report['date'] is "YYYY-MM-DD HH:MM"
            day_reports = [r for r in reports if r['date'].startswith(date_str)]
            
            if not day_reports:
                continue
                
            # Take the first one (assuming sorted desc)
            last_report = day_reports[0]
            filename = last_report['filename']
            file_path = f"data/{filename}"
            # Or if filename is absolute/relative? scraper logic saves to current dir usually.
            # But scraper.py says: filename_prefix = f"trending_integrated" -> saved in current dir.
            # check if file exists
            if not os.path.exists(filename) and os.path.exists(os.path.join('data', filename)):
                 filename = os.path.join('data', filename)
            
            if os.path.exists(filename):
                try:
                    if filename.endswith('.csv'):
                        df = pd.read_csv(filename)
                    elif filename.endswith('.xlsx'):
                        df = pd.read_excel(filename)
                    else:
                        continue
                    
                    # Store
                    daily_dfs[date_str] = df
                except Exception as e:
                    print(f"[5Day] Error loading {filename}: {e}")
                    
    except Exception as e:
        print(f"[5Day] Error reading reports.json: {e}")
        
    return daily_dfs

def analyze_5days():
    """
    Main function to perform 5-day analysis.
    Returns: DataFrame (Analysis Result)
    """
    print("\n[5Day Analysis] Starting...")
    
    # 1. Identify Target Dates
    target_dates = get_recent_working_days(5) 
    print(f"[5Day Analysis] Target Dates: {target_dates}")
    
    # 2. Load Data
    daily_dfs = load_daily_snapshots(target_dates) # {date: df}
    if not daily_dfs:
        print("[5Day Analysis] No data found for target dates.")
        return pd.DataFrame()

    # 3. Aggregate Data
    # We need a master list of all unique stock codes that appeared in these files.
    all_codes = set()
    for date_str, df in daily_dfs.items():
        if 'code' in df.columns:
            # Ensure code is string and 6 digits
            df['code'] = df['code'].astype(str).str.zfill(6)
            all_codes.update(df['code'].tolist())
            
    if not all_codes:
        return pd.DataFrame()
        
    records = []
    
    # target_dates[0] is Today (Latest)
    # target_dates[1] is Yesterday, etc.
    # Order: [Today, D-1, D-2, D-3, D-4]
    
    for code in all_codes:
        # Check presence and stats for each day
        stats_by_day = [] # List of tuples/dicts
        
        consecutive_days = 0 
        is_consecutive_broken = False
        
        total_posts = 0
        posts_list = []
        change_rates = []
        prices = []
        
        # Meta info from the LATEST available appearance
        latest_meta = {}
        found_in_today = False
        
        # We iterate from Today backwards for Consecutive count
        for i, date_str in enumerate(target_dates):
            df = daily_dfs.get(date_str)
            
            if df is not None and not df.empty and 'code' in df.columns:
                row = df[df['code'] == code]
                if not row.empty:
                    # Stock exists on this day
                    data = row.iloc[0]
                    
                    # Capture meta if it's the first time we see it (Most recent data)
                    if not latest_meta:
                            'name': data.get('name') or data.get('종목명', ''),
                            'market': data.get('market') or data.get('시장구분', ''), 
                            'price': data.get('price') or data.get('현재가', 0),
                            'change_rate': data.get('change_rate') or data.get('등락률', '0%'),
                            'code': code
                        }
                    
                    if i == 0:
                        found_in_today = True

                    # Consecutive Check
                    if not is_consecutive_broken:
                        consecutive_days += 1
                        
                    # Stats
                    p_count = int(data.get('recent_posts_count') or data.get('당일_게시글수', 0))
                    total_posts += p_count
                    posts_list.append(p_count)
                    
                    c_rate = str(data.get('change_rate') or data.get('등락률', '0%')).replace('%', '')
                    try:
                        change_rates.append(float(c_rate))
                    except:
                        change_rates.append(0.0)
                        
                    p_price = str(data.get('price') or data.get('현재가', '0')).replace(',', '')
                    prices.append(p_price)
                        
                else:
                    # Stock NOT present on this day
                    if not is_consecutive_broken:
                        # Before breaking, special case:
                        # If today is target_dates[0], and stock is NOT in today, consecutive is 0?
                        # Or do we count backward from the last time it appeared?
                        # User requirement: "연속 등록일 수"
                        # Usually implies "Present Today + Present Yesterday...".
                        # If not present today, consecutive might be 0 or check if present yesterday?
                        # Let's be strict: consecutively present *ending at the latest capture*.
                        # If not in today (idx 0), consecutive is 0. 
                        # Wait, "Calculated based on today's latest data".
                        # If it's not in today's list, it's gathered from 5 days history.
                        # So if it was present D-1, D-2, but not Today -> Consecutive = 0.
                        is_consecutive_broken = True
                    
                    # Missing day data treatment for stats?
                    # " 누적 5일간 차트에 들어갔던 모든 종목"
                    # If missing, post count is 0?
                    posts_list.append(0)
                    change_rates.append(0.0) # Or None? Sparkline needs value. 0 is fine for chart?
            else:
                 # No data for this entire day (e.g. file missing)
                 is_consecutive_broken = True
                 posts_list.append(0)
                 change_rates.append(0.0)
        
        # If no meta found (shouldn't happen if in all_codes), skip
        if not latest_meta:
            continue
            
        # Standard Deviation
        import statistics
        avg_posts = total_posts / 5 # fixed 5 days average or days present? "5일간...평균" -> /5 usually
        if len(posts_list) > 1:
            std_dev = statistics.stdev(posts_list)
        else:
            std_dev = 0
            
        record = {
            'code': code,
            'name': latest_meta.get('name'),
            'market': latest_meta.get('market'),
            'price': latest_meta.get('price'),
            'change_rate': latest_meta.get('change_rate'), # Latest change rate
            'consecutive_days': consecutive_days,
            'total_posts': total_posts,
            'avg_posts': round(avg_posts, 1),
            'std_dev': round(std_dev, 1),
            'sparkline': change_rates[::-1] # Reverse to be Chronological [D-4, ..., D-0] for chart
        }
        records.append(record)
        
    # Create DF
    result_df = pd.DataFrame(records)
    
    # Sort by Consecutive Days Desc
    if not result_df.empty:
        result_df = result_df.sort_values(by=['consecutive_days', 'total_posts'], ascending=[False, False])
        
    print(f"[5Day Analysis] Processed {len(result_df)} stocks.")
    return result_df

if __name__ == "__main__":
    # Test run
    df = analyze_5days()
    print(df.head())
    # print(df.to_json(orient='records', force_ascii=False))
