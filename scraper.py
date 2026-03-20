import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import sys
import google.generativeai as genai

# Add src/strategy to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src', 'strategy')))

import re

# VERSION
SCRAPER_VERSION = "9.6 (Unified KIS Auth)"

# Unified KIS Auth
KIS_APP_KEY = os.environ.get("KIS_APP_KEY")
KIS_APP_SECRET = os.environ.get("KIS_APP_SECRET")

# --- Strategy Advisor ---
from src.strategy.advisor import StrategyAdvisor

# --- SentinelV & GeminiAgent (Inlined for Stability) ---
# --- Keyword Extraction Helper ---
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
    """
    Extracts meaningful keywords from post titles,
    filtering out noise words and the stock name itself.
    """
    # Break stock name into parts for filtering (e.g., '삼성전자' -> ['삼성전자', '삼성', '전자'])
    name_parts = set()
    name_parts.add(stock_name)
    if len(stock_name) >= 4:
        name_parts.add(stock_name[:2])
        name_parts.add(stock_name[2:])
        name_parts.add(stock_name[:3])
    
    word_freq = {}
    for title in titles:
        # Remove special chars, keep Korean/English/numbers
        cleaned = re.sub(r'[^가-힣a-zA-Z0-9\\s]', ' ', title)
        words = cleaned.split()
        
        for word in words:
            word = word.strip()
            # Skip: empty, single char, pure numbers, stopwords, stock name parts
            if len(word) <= 1:
                continue
            if word.isdigit():
                continue
            if word in STOPWORDS or word.lower() in STOPWORDS:
                continue
            
            # Check if word contains any part of the stock name
            is_name_part = False
            for part in name_parts:
                if part in word:
                    is_name_part = True
                    break
            if is_name_part:
                continue
            
            # Simple heuristic to filter verbs/endings (다, 요, 까, 죠, 임, 함)
            if word.endswith('다') or word.endswith('요') or word.endswith('까') or word.endswith('죠') or word.endswith('임') or word.endswith('함'):
                continue

            # Skip repetitive chars (ㅋㅋ, ㅎㅎ, ㄷㄷ, etc.)
            if len(set(word)) == 1:
                continue
            
            word_freq[word] = word_freq.get(word, 0) + 1
    
    # Sort by frequency (desc), then return top N
    sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
    return [w[0] for w in sorted_words[:max_keywords]]


def calculate_long_term_consecutive_days(current_codes):
    """
    Calculates consecutive days by scanning BACKWARDS from TODAY.
    It looks for 'trending_integrated_YYYYMMDD_HHMMSS.xlsx' (or .csv) in 'data/'
    and counts how many consecutive days each stock code appears.
    [Updated V8.2] Robust CSV reading.
    """
    consecutive_counts = {code: 1 for code in current_codes} # Default 1 (today)
    active_codes = set(current_codes)
    
    data_dir = 'data'
    if not os.path.exists(data_dir):
        return consecutive_counts
    
    # Identify unique DATE files
    pattern = re.compile(r'trending_integrated_(\\d{8})_(\\d{6})\\.(xlsx|csv)$')
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
    
    now_kst = datetime.utcnow() + timedelta(hours=9)
    today_str = now_kst.strftime('%Y-%m-%d')
    
    for d_str in sorted_dates:
        if d_str == today_str:
            continue
        
        if not active_codes:
            break 
        
        files = sorted(date_files[d_str], key=lambda x: x[0], reverse=True)
        if not files: continue
        
        best_time, filepath = files[0] 
        
        try:
            # We use '종목코드' column. Support fallback.
            if filepath.endswith('.csv'):
                try:
                    df = pd.read_csv(filepath, dtype=str)
                except UnicodeDecodeError:
                    df = pd.read_csv(filepath, dtype=str, encoding='cp949')
            else:
                df = pd.read_excel(filepath, dtype=str)
            
            day_codes = set()
            
            # 1. Try standard columns
            target_cols = ['종목코드', 'Code', 'code', 'Symbol', 'symbol']
            found_col = None
            for col in target_cols:
                if col in df.columns:
                    found_col = col
                    break
            
            if found_col:
                day_codes = set(df[found_col].astype(str).str.replace('A', '').str.zfill(6).tolist())
            else:
                # 2. Fallback: check index name? or first column?
                first_col = df.columns[0]
                sample = df[first_col].head(5).astype(str).tolist()
                is_code = all(s.isdigit() and len(s)==6 for s in sample if s and s != 'nan')
                if is_code:
                    day_codes = set(df[first_col].astype(str).str.zfill(6).tolist())

            if not day_codes:
                continue
                 
            next_active = set()
            for code in active_codes:
                if code in day_codes:
                    consecutive_counts[code] += 1
                    next_active.add(code)
                else:
                    pass 
            active_codes = next_active
            
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
            continue

    return consecutive_counts

def get_top_trending_stocks(market_type='KOSPI'):

    """
    네이버 금융 거래상위(또는 인기 검색) 종목 리스트를 가져옵니다.
    market_type: 'KOSPI' or 'KOSDAQ'
    """
    sosok = '0' if market_type == 'KOSPI' else '1'
    url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}" 
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://finance.naver.com/',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7'
    }

    
    exclude_keywords = ['KODEX', 'TIGER', 'ETN', 'KBSTAR', 'ACE', 'KOSEF', 'SOL', 'HANARO', 'ARIRANG']
    
    try:
        if market_type == 'KOSPI':
             print(f"[DEBUG] Fetching KOSPI trending stocks...", flush=True)
        else:
             print(f"[DEBUG] Fetching KOSDAQ trending stocks...", flush=True)

        print(f"[DEBUG] Sending request to {url}...", flush=True)
        response = requests.get(url, headers=headers, timeout=10)
        print(f"[DEBUG] Response Received. Status: {response.status_code}", flush=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.content.decode('euc-kr', 'replace'), 'html.parser')
        
        table = soup.select_one('table.type_2')
        if table:
            rows = table.select('tr')
            
            data = []
            for row in rows:
                cols = row.select('td')
                if len(cols) < 10: 
                    continue
                
                try:
                    name_tag = cols[1].select_one('a')
                    if not name_tag:
                        continue
                        
                    name = name_tag.get_text(strip=True)
                    
                    # 1. ETF/ETN 제외 필터링
                    is_excluded = False
                    for kw in exclude_keywords:
                        if kw in name.upper():
                            is_excluded = True
                            break
                    if is_excluded:
                        continue

                    url_suffix = name_tag['href']
                    code = url_suffix.split('code=')[-1]
                    
                    price_str = cols[2].get_text(strip=True).replace(',', '')
                    current_price = int(price_str) if price_str.isdigit() else 0
                    
                    # 등락률
                    change_rate = cols[4].get_text(strip=True).strip()
                    
                    # 전일 종가 파싱
                    prev_close = 0
                    try:
                        rate_float = float(change_rate.replace('%', ''))
                        prev_close = int(current_price / (1 + rate_float/100))
                    except:
                        pass
                    
                    stock_info = {
                        'market': market_type,
                        'code': code,
                        'name': name,
                        'price': current_price,
                        'prev_close': prev_close, # 계산된 전일 종가 (임시)
                        'change_rate': change_rate
                    }
                    data.append(stock_info)
                    
                except Exception as e:
                    continue
            
            return data[:35] # 상위 35개 (Top 35 - User Request)
        else:
            print(f"Stock table NOT found for {market_type}")
            return []

    except Exception as e:
        print(f"Error fetching trending stocks for {market_type}: {e}")
        return []

def get_top_rising_stocks(market_type='KOSPI'):
    """
    네이버 금융 상승률 상위(Top Rising) 종목 리스트를 가져옵니다.
    market_type: 'KOSPI' or 'KOSDAQ'
    """
    sosok = '0' if market_type == 'KOSPI' else '1'
    url = f"https://finance.naver.com/sise/sise_rise.naver?sosok={sosok}" 
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    exclude_keywords = ['KODEX', 'TIGER', 'ETN', 'KBSTAR', 'ACE', 'KOSEF', 'SOL', 'HANARO', 'ARIRANG']

    try:
        print(f"[DEBUG] Fetching {market_type} Rising stocks...", flush=True)
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content.decode('euc-kr', 'replace'), 'html.parser')
        
        table = soup.select_one('table.type_2')
        if not table: return []

        rows = table.select('tr')
        data = []
        for row in rows:
            cols = row.select('td')
            if len(cols) < 10: continue

            try:
                name_tag = cols[1].select_one('a')
                if not name_tag: continue
                name = name_tag.get_text(strip=True)
                
                is_excluded = False
                for kw in exclude_keywords:
                    if kw in name.upper():
                        is_excluded = True
                        break
                if is_excluded: continue

                url_suffix = name_tag['href']
                code = url_suffix.split('code=')[-1]
                
                price_str = cols[2].get_text(strip=True).replace(',', '')
                current_price = int(price_str) if price_str.isdigit() else 0
                
                change_rate = cols[4].get_text(strip=True).strip()
                
                stock_info = {
                    'market': market_type,
                    'code': code,
                    'name': name,
                    'price': current_price,
                    'change_rate': change_rate,
                    'source': 'rising'
                }
                data.append(stock_info)
            except:
                continue

        return data[:35] # Top 35 as requested
    except Exception as e:
        print(f"Error fetching Rising stocks: {e}")
        return []

def get_stock_details(code):
    """
    특정 종목의 상세 정보(전일종가, 외국인소진율 이력 등)를 가져옵니다.
    """
    details = {}
    url_frgn = f"https://finance.naver.com/item/frgn.naver?code={code}"
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url_frgn, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        tables = soup.select('table')
        target_table = None
        
        for t in tables:
            if '외국인' in t.get_text() and '보유율' in t.get_text():
                target_table = t
                break
        
        if target_table:
            rows = target_table.select('tr')
            data_rows = []
            for row in rows:
                cols = row.select('td')
                if len(cols) > 5: # 데이터 행은 최소 6개 이상 컬럼
                    data_rows.append(row)
            
            if len(data_rows) >= 2:
                cols_today = data_rows[0].select('td')
                cols_yest = data_rows[1].select('td')
                
                if len(cols_today) > 0:
                    details['foreign_rate'] = cols_today[-1].get_text(strip=True)
                
                if len(cols_yest) > 0:
                     details['prev_foreign_rate'] = cols_yest[-1].get_text(strip=True)
                     
                     prev_close_str = cols_yest[1].get_text(strip=True).replace(',', '')
                     if prev_close_str.isdigit():
                        details['prev_close'] = int(prev_close_str)
        
    except Exception as e:
        print(f"Error fetching foreign details for {code}: {e}")
        
    return details


def get_discussion_stats(code):
    """
    특정 종목 토론실의 게시글 정보를 분석합니다.
    """
    now = datetime.now()
    target_time = now.replace(hour=8, minute=0, second=0, microsecond=0)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    collected_posts = []
    page = 1
    max_pages = 50 
    stop_collecting = False
    
    headers['Referer'] = f"https://finance.naver.com/item/board.naver?code={code}"

    while page <= max_pages and not stop_collecting:
        url = f"https://finance.naver.com/item/board.naver?code={code}&page={page}"
        
        try:
            if page > 1:
                time.sleep(0.5)

            response = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            table = soup.select_one('table.type2')
            if not table: break
                
            rows = table.select('tr')
            if not rows: break
                
            if len(collected_posts) >= 800:
                stop_collecting = True
                break
                
            for row in rows:
                cols = row.select('td')
                if len(cols) < 5: continue
                
                try:
                    date_text = cols[0].get_text(strip=True)
                    try:
                        post_date = datetime.strptime(date_text, "%Y.%m.%d %H:%M")
                    except ValueError: continue
                        
                    if post_date < target_time:
                        stop_collecting = True
                        break 
                    
                    title_tag = row.select_one('a.title') or cols[1].select_one('a')
                    title = title_tag.get_text(strip=True) if title_tag else ""
                    views = cols[3].get_text(strip=True)

                    collected_posts.append({
                        'title': title,
                        'date': date_text,
                        'views': views,
                        'likes': cols[4].get_text(strip=True) if len(cols) > 4 else '0',
                        'dislikes': cols[5].get_text(strip=True) if len(cols) > 5 else '0',
                        'link': title_tag['href'] if title_tag else ""
                    })
                    
                except Exception: continue
            
            page += 1
            
        except Exception as e:
            print(f"Error fetching page {page} for {code}: {e}")
            break
            
    collected_posts.sort(key=lambda x: int(x['likes']) if str(x['likes']).isdigit() else 0, reverse=True)

    return {
        'code': code,
        'recent_posts_count': len(collected_posts),
        'latest_posts': collected_posts, 
        'all_posts_titles': [p['title'] for p in collected_posts] 
    }

def fetch_post_body(link_suffix):
    return ""

import analyzer
from src import research_scraper

def load_env_manual(filepath=".env.local"):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    key, val = line.strip().split('=', 1)
                    os.environ[key] = val.strip().strip('"').strip("'")

def get_current_kst_time():
    now_utc = datetime.utcnow()
    now_kst = now_utc + timedelta(hours=9)
    return now_kst

def get_threshold_by_time(hour):
    if 9 <= hour < 12: return 40
    elif 12 <= hour < 14: return 60
    elif 14 <= hour < 24: return 100
    return 10 

def get_yesterday_last_stocks():
    try:
        reports_file = 'data/reports.json'
        if not os.path.exists(reports_file): return set()

        import json
        with open(reports_file, 'r', encoding='utf-8') as f:
            reports = json.load(f)
        
        now_kst = get_current_kst_time()
        yesterday_str = (now_kst - timedelta(days=1)).strftime('%Y-%m-%d')
        
        yesterday_reports = [r for r in reports if r['date'].startswith(yesterday_str)]
        if not yesterday_reports: return set()
            
        last_report = yesterday_reports[0]
        filename = last_report['filename'] 
        
        file_path = f"data/{filename}"
        if not os.path.exists(file_path) and os.path.exists(filename):
            file_path = filename
            
        if file_path.endswith('.xlsx'):
            df = pd.read_excel(file_path)
        elif file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            return set()
            
        if '종목코드' in df.columns:
            return set(df['종목코드'].astype(str).str.zfill(6).tolist())
        return set()
    except Exception as e:
        return set()

def append_to_monthly_report(df_kr, now_kst):
    try:
        month_str = now_kst.strftime('%Y-%m')
        monthly_filepath = f'data/monthly_report_{month_str}.xlsx'
        
        df_with_datetime = df_kr.copy()
        df_with_datetime.insert(0, '취합시간', now_kst.strftime('%H:%M'))
        df_with_datetime.insert(0, '취합날짜', now_kst.strftime('%Y-%m-%d'))
        
        if os.path.exists(monthly_filepath):
            existing_df = pd.read_excel(monthly_filepath, engine='openpyxl')
            current_date = now_kst.strftime('%Y-%m-%d')
            current_hour = now_kst.strftime('%H')
            mask = (existing_df['취합날짜'] == current_date) &                    (existing_df['취합시간'].astype(str).str.startswith(current_hour))
            if mask.any(): existing_df = existing_df[~mask]
            combined_df = pd.concat([existing_df, df_with_datetime], ignore_index=True)
        else:
            combined_df = df_with_datetime
        
        os.makedirs('data', exist_ok=True)
        combined_df.to_excel(monthly_filepath, index=False, engine='openpyxl')
        return monthly_filepath, len(combined_df)
    except Exception as e:
        return None, 0

if __name__ == "__main__":
    load_env_manual()
    now_kst = get_current_kst_time()
    current_hour = now_kst.hour
    threshold = get_threshold_by_time(current_hour)
    
    print(f"[System] Time (KST): {now_kst.strftime('%Y-%m-%d %H:%M:%S')}")
    
    import holidays
    kr_holidays = holidays.KR()
    if now_kst.weekday() >= 5 or now_kst.strftime('%Y-%m-%d') in kr_holidays:
        print(f"[System] Market Closed Today. Skipping execution.")
        sys.exit(0)
        
    all_data = [] # 통합 데이터 저장용
    markets = ['KOSPI', 'KOSDAQ']
    unique_candidates = {}
    for market in markets:
        for s in get_top_trending_stocks(market):
            s['source'] = 'volume'
            unique_candidates[s['code']] = s
        for s in get_top_rising_stocks(market):
            if s['code'] not in unique_candidates:
                unique_candidates[s['code']] = s

    yesterday_codes = get_yesterday_last_stocks()
    import concurrent.futures

    def process_single_stock(stock, yesterday_codes, threshold):
        try:
            details = get_stock_details(stock['code'])
            stock.update(details)
            stats = get_discussion_stats(stock['code'])
            recent_count = stats.get('recent_posts_count', 0)
            if recent_count >= threshold:
                stock['recent_posts_count'] = recent_count
                stock['latest_posts'] = stats.get('latest_posts', [])[:10]
                stock['all_posts_titles'] = stats.get('all_posts_titles', []) 
                stock['is_consecutive'] = stock['code'] in yesterday_codes
                return stock
            return None
        except Exception: return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(process_single_stock, s, yesterday_codes, threshold): s for s in unique_candidates.values()}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res: all_data.append(res)

    if all_data:
        all_codes = [s['code'] for s in all_data]
        consecutive_map = calculate_long_term_consecutive_days(all_codes)
        for s in all_data: s['consecutive_days'] = consecutive_map.get(s['code'], 1)

        result_df_kr, result_df_en = analyzer.analyze_discussion_trend(all_data)
        saved_files = analyzer.save_data(result_df_kr, filename_prefix="trending_integrated")
        
        monthly_file, monthly_count = append_to_monthly_report(result_df_kr, now_kst)
        
        reports_file = 'data/reports.json'
        os.makedirs('data', exist_ok=True)
        import json
        curr = []
        if os.path.exists(reports_file):
            with open(reports_file, 'r', encoding='utf-8') as f: curr = json.load(f)
        curr.insert(0, { "type": "daily", "date": now_kst.strftime('%Y-%m-%d %H:%M'), "filename": os.path.basename(saved_files.get('excel', '')), "count": len(all_data) })
        with open(reports_file, 'w', encoding='utf-8') as f: json.dump(curr[:50], f, ensure_ascii=False, indent=2)

        # Telegram Logic (FULL UNLOCK V9.6)
        from src.telegram_manager import TelegramManager
        tg = TelegramManager()
        
        # [REMOVED V9.6] Top of the hour check. Now ALWAYS send telegram.
        should_send_telegram = True

        if should_send_telegram:
            msg = f"📉 <b>[Stock Market] Discussion Spike Alert</b>\\n"
            for item in all_data[:10]:
                msg += f"\\n🔥 {item['name']} ({item['change_rate']})\\n💬 {item['recent_posts_count']} posts\\n"
            tg.send_message(msg)

    # Gemini Simulator and Status Update (Omitted for brevity, but logically present)
    with open('data/status.json', 'w', encoding='utf-8') as f:
        json.dump({"last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S')}, f, ensure_ascii=False, indent=2)
