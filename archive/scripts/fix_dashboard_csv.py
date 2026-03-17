import json
import pandas as pd
import os
import glob

# 1. Load latest_stocks.json (English Data)
try:
    with open('data/latest_stocks.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f"Loaded {len(data)} records from latest_stocks.json")
    
    # Convert to DataFrame
    df = pd.DataFrame(data)
    print("DataFrame columns:", df.columns.tolist())
    
    # 2. Find the latest trending_integrated CSV
    csv_files = glob.glob('data/trending_integrated_*.csv')
    if not csv_files:
        print("No CSV files found.")
        exit()
        
    latest_csv = max(csv_files, key=os.path.getctime)
    print(f"Latest CSV found: {latest_csv}")
    
    # 3. Overwrite with English DataFrame
    # Ensure columns order if relevant, but typically Dashboard reads by key/header name
    # The standard columns in scraper.py:
    # market, code, name, price, foreign_rate, prev_close, prev_foreign_rate, change_rate, recent_posts_count, posts_summary, sentiment, top_keywords, is_last_captured, (optional) latest_posts
    
    # 'latest_posts' is a list of dicts, might mess up CSV if not handled, but check if original CSV had it.
    # Usually CSV dumps it as string or excludes it.
    # scraper.py uses analyzer.save_data -> to_csv.
    
    # Let's just save.
    df.to_csv(latest_csv, index=False, encoding='utf-8-sig')
    print(f"Overwrote {latest_csv} with English data.")
    
    # Verify headers
    ver_df = pd.read_csv(latest_csv)
    print("New CSV Headers:", ver_df.columns.tolist())

except Exception as e:
    print(f"Error: {e}")
