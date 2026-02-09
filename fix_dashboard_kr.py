import json
import pandas as pd
import os
import glob
from datetime import datetime

# Mapping for English -> Korean (Exact Match to User Screenshot)
eng_to_kor = {
    'market': '시장구분',
    'name': '종목명',
    'price': '현재가',
    'foreign_rate': '현재_외국인비중',
    'prev_close': '어제_종가',
    'prev_foreign_rate': '어제_외국인비중',
    'change_rate': '등락률',
    'recent_posts_count': '당일_게시글수',
    'posts_summary': '게시물_요약',
    'sentiment': '감정분석',
    'top_keywords': 'Top_Keyword',
    'is_last_captured': '연속_등록',
    'latest_posts': 'latest_posts',
    'code': 'code'
}

# Desired Order (Matches Screenshot)
desired_order_en = [
    'name', 'price', 'change_rate', 'recent_posts_count', 'foreign_rate', 'market',
    'prev_close', 'prev_foreign_rate', 'posts_summary', 
    'sentiment', 'top_keywords', 'is_last_captured', 'latest_posts', 'code'
]

# 1. Load latest_stocks.json
try:
    with open('data/latest_stocks.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f"Loaded {len(data)} records from latest_stocks.json")
    
    # Convert to DataFrame
    df = pd.DataFrame(data)
    
    # Check if keys are already Korean (from previous run) or English
    # If Korean ("시장구분"), we need to map them to New Korean ("시장")
    # Using a flexible approach: normalize to English first if possible, or just map known Korean keys to New Korean Keys
    
    # Map Old Korean -> New Korean if needed
    old_kor_to_new_kor = {
        '시장': '시장구분',
        '외인소진율': '현재_외국인비중',
        '게시글수': '당일_게시글수'
    }
    df = df.rename(columns=old_kor_to_new_kor)
    
    # Map English -> New Korean (if any English keys remain)
    df = df.rename(columns=eng_to_kor)
    
    # Reorder columns
    # We need to list the KOREAN column names corresponding to desired_order_en
    desired_cols_kr = []
    for col in desired_order_en:
        kr_name = eng_to_kor.get(col, col) # Get Korean name or keep English
        if kr_name in df.columns:
            desired_cols_kr.append(kr_name)
    
    # Add any other columns not in desired list
    for col in df.columns:
        if col not in desired_cols_kr:
            desired_cols_kr.append(col)
            
    df = df[desired_cols_kr]
    
    print("New Corrected Columns:", df.columns.tolist())
    
    # 3. Create a NEW CSV filename
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    new_csv = f"data/trending_integrated_{now_str}.csv"
    
    # 4. Save to CSV
    df.to_csv(new_csv, index=False, encoding='utf-8-sig')
    print(f"Created new CSV: {new_csv}")
    
    # 5. Save to latest_stocks.json
    import math
    def sanitize_for_json(obj):
        if isinstance(obj, dict): return {k: sanitize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list): return [sanitize_for_json(item) for item in obj]
        if pd.isna(obj): return None
        elif isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj): return None
            return obj
        return obj

    clean_records = sanitize_for_json(df.to_dict('records'))
    
    with open('data/latest_stocks.json', 'w', encoding='utf-8') as f:
        json.dump(clean_records, f, ensure_ascii=False, indent=4)
    print("Overwrote data/latest_stocks.json with Screenshot-Matching keys.")
    
    # Also overwrite all_stocks.json
    with open('data/all_stocks.json', 'w', encoding='utf-8') as f:
        json.dump(clean_records, f, ensure_ascii=False, indent=4)
        
except Exception as e:
    print(f"Error: {e}")
