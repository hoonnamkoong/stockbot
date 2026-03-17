
import json
import os
import pandas as pd
import sys
import re
from datetime import datetime, timedelta

# --- COPIED FROM scraper.py ---
STOPWORDS = {
    '오늘', '어제', '내일', '지금', '현재', '실시간', '속보', '긴급',
    '주식', '종목', '매수', '매도', '매매', '투자', '주가', '가격',
    '상한가', '하한가', '급등', '급락', '폭등', '폭락', '상승', '하락',
    '정보', '분석', '전망', '예상', '의견', '생각', '질문', '궁금',
    '여기', '저기', '이거', '저거', '그거', '뭐', '왜', '어떻게',
    '진짜', '정말', '완전', '너무', '진심', '대박', '헐', '와',
    '사람', '분들', '여러분', '우리', '나', '제가', '내가',
    '합니다', '입니다', '습니다', '됩니다', '같습니다', '봅니다',
    '하는', '것', '수', '중', '후', '전', '때', '더', '안', '못',
    '좀', '잘', '다', '또', '그냥', '아직', '이미', '계속', '다시',
    '보세요', '하세요', '드립니다', '감사', '부탁', '제발',
    '코스피', '코스닥', 'KOSPI', 'KOSDAQ',
    '원', '만원', '천원', '억', '조', '퍼센트',
    '오늘도', '오늘은', '어제도', '내일도', '지금은', '현재가', '목표가', '매수가', '매도가',
    'ㅋㅋ', 'ㅋㅋㅋ', 'ㅋㅋㅋㅋ', 'ㅎㅎ', 'ㅎㅎㅎ', 'ㄷㄷ', 'ㄷㄷㄷ',
    '공시', '뉴스', '속보', '특징주', '단독', '상보', '종합', '오후', '오전'
}

def extract_meaningful_keywords(titles, stock_name, max_keywords=5):
    # Break stock name into parts
    name_parts = set()
    name_parts.add(stock_name)
    if len(stock_name) >= 4:
        name_parts.add(stock_name[:2])
        name_parts.add(stock_name[2:])
        name_parts.add(stock_name[:3])
    
    word_freq = {}
    for title in titles:
        cleaned = re.sub(r'[^가-힣a-zA-Z0-9\s]', ' ', title)
        words = cleaned.split()
        
        for word in words:
            word = word.strip()
            if len(word) <= 1: continue
            if word.isdigit(): continue
            if word in STOPWORDS or word.lower() in STOPWORDS: continue
            
            is_name_part = False
            for part in name_parts:
                if part in word:
                    is_name_part = True
                    break
            if is_name_part: continue

            if word.endswith('다') or word.endswith('요') or word.endswith('까') or word.endswith('죠') or word.endswith('임') or word.endswith('함'):
                continue

            if len(set(word)) == 1: continue
            
            word_freq[word] = word_freq.get(word, 0) + 1
    
    sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
    return [w[0] for w in sorted_words[:max_keywords]]

def calculate_long_term_consecutive_days(current_codes):
    """
    Calculates consecutive days by scanning BACKWARDS from TODAY (or latest data).
    It looks for 'trending_integrated_YYYYMMDD_HHMMSS.xlsx' (or .csv) in 'data/'
    and counts how many consecutive days each stock code appears.
    """
    consecutive_counts = {code: 1 for code in current_codes} # Default 1 (today)
    active_codes = set(current_codes)
    
    data_dir = 'data'
    if not os.path.exists(data_dir):
        print(f"DEBUG: {data_dir} does not exist.")
        return consecutive_counts
    
    # Identify unique DATE files
    # Pattern: trending_integrated_YYYYMMDD_HHMMSS.xlsx
    pattern = re.compile(r'trending_integrated_(\d{8})_(\d{6})\.(xlsx|csv)$')
    date_files = {} # { '2025-01-01': [('120000', path), ('150000', path)] }
    
    for filename in os.listdir(data_dir):
        match = pattern.match(filename)
        if match:
            # Parse Date
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
            
    # Sort dates descending (yesterday, day before...)
    sorted_dates = sorted(date_files.keys(), reverse=True)
    
    # Determine "Today" (to skip if the run is today)
    # Since we are running this script NOW, let's assume we want to count back from "latest available date in data"
    # Note: If latest_stocks.json is from Today, we skip Today's history file to avoid double counting?
    # Logic: consecutive_counts starts at 1 (for the current session). 
    # We check YESTERDAY. If present, +1. Then DAY BEFORE. If present, +1.
    # The 'sorted_dates' includes TODAY potentially.
    # If we find files for TODAY, we should SKIP them because 'current_codes' IS today's data.
    
    now_kst = datetime.utcnow() + timedelta(hours=9)
    today_str = now_kst.strftime('%Y-%m-%d')
    print(f"DEBUG: Today is {today_str}")
    print(f"DEBUG: Found history dates: {sorted_dates}")
    
    for d_str in sorted_dates:
        if d_str == today_str:
            print(f"DEBUG: Skipping today's history file ({d_str})")
            continue
        
        if not active_codes:
            break # No more codes to check
        
        # Get the LATEST file for that day (most complete)
        files = sorted(date_files[d_str], key=lambda x: x[0], reverse=True)
        if not files: continue
        
        best_time, filepath = files[0] # (time, path)
        print(f"DEBUG: Checking {d_str} using {filepath}...")
        
        try:
            # Read file (only '종목코드' column needed)
            # Support CSV and Excel
            if filepath.endswith('.csv'):
                try:
                    df = pd.read_csv(filepath, usecols=['종목코드'], dtype={'종목코드': str})
                except ValueError:
                     # Maybe encoding issue?
                     df = pd.read_csv(filepath, usecols=['종목코드'], dtype={'종목코드': str}, encoding='cp949')
            else:
                df = pd.read_excel(filepath, usecols=['종목코드'], dtype={'종목코드': str})
            
            if '종목코드' in df.columns:
                 # Normalize codes (remove 'A', zfill)
                 day_codes = set(df['종목코드'].astype(str).str.replace('A', '').str.zfill(6).tolist())
            else:
                 day_codes = set()
                 
            # Check presence
            next_active = set()
            for code in active_codes:
                if code in day_codes:
                    consecutive_counts[code] += 1
                    next_active.add(code)
                else:
                    # Streak broken
                    pass 
            active_codes = next_active
            
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
            continue

    return consecutive_counts

# --- VERIFICATION LOGIC ---
    # Print to stdout with flush
    print("--- START VERIFICATION ---", flush=True)
    
    # 1. Keywords
    try:
        with open('data/latest_stocks.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        bad_count = 0
        for stock in data[:50]:
            kws = stock.get('top_keywords', '')
            for k in kws.split(', '):
                if k.strip() in STOPWORDS:
                    bad_count += 1
        
        if bad_count > 0:
            print(f"KEYWORDS: FAIL (Bad Count: {bad_count})", flush=True)
        else:
            print("KEYWORDS: PASS", flush=True)

    except Exception as e:
        print(f"KEYWORDS: CRASH ({e})", flush=True)

    # 2. CSV Header Check
    try:
        data_dir = 'data'
        files = [f for f in os.listdir(data_dir) if f.startswith('trending_integrated') and f.endswith('.csv')]
        if files:
            latest = sorted(files)[-1]
            path = os.path.join(data_dir, latest)
            # Read first line
            with open(path, 'r', encoding='cp949', errors='ignore') as f:
                header = f.readline().strip()
            print(f"CSV_HEADER: {header}", flush=True)
            
            # Check if '종목코드' is in header
            if '종목코드' in header:
                print("CSV_COL_CHECK: PASS", flush=True)
            else:
                print("CSV_COL_CHECK: FAIL", flush=True)
        else:
            print("CSV_CHECK: NO CSV FILES", flush=True)
            
    except Exception as e:
        print(f"CSV_CHECK: CRASH ({e})", flush=True)

    # 3. Consecutive
    try:
        codes = [s['code'] for s in data]
        consecutive_map = calculate_long_term_consecutive_days(codes)
        gt_1_count = sum(1 for v in consecutive_map.values() if v > 1)
        
        if gt_1_count > 0:
            print(f"CONSECUTIVE: PASS (Count > 0: {gt_1_count})", flush=True)
        else:
            print("CONSECUTIVE: FAIL (All are 1)", flush=True)
            
    except Exception as e:
        print(f"CONSECUTIVE: CRASH ({e})", flush=True)

    print("--- END VERIFICATION ---", flush=True)
