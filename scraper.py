import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import sys
import google.generativeai as genai

import re

# VERSION
SCRAPER_VERSION = "9.1 (Inlined Sentinel)"

# --- SentinelV & GeminiAgent (Inlined for Stability) ---
class SentinelV:
    """
    Technical Analysis Sentinel (Updated V9.0 - Inlined)
    Analyzes stock data to generate BUY/SELL signals based on reinforced logic.
    """
    def __init__(self):
        self.history_file = 'data/sentinel_history.json'
        self.history = self._load_history()

    def _load_history(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def analyze_stock(self, stock, threshold=None):
        """
        Analyzes a single stock and returns (signal, reason).
        Signal: "BUY_STRONG", "BUY", "SELL", "SELL_STRONG", or "None"
        threshold: The dynamic post count criteria used for this run (e.g., 40, 60, 100).
        """
        signal = "None"
        reason = ""

        # Default fallback if threshold not provided
        if threshold is None:
            # Simple time-based fallback (KST)
            current_hour = (datetime.utcnow().hour + 9) % 24
            if 9 <= current_hour < 12: threshold = 40
            elif 12 <= current_hour < 14: threshold = 60
            elif 14 <= current_hour < 24: threshold = 100
            else: threshold = 10


        try:
            name = stock.get('name', '')
            price = float(stock.get('price', 0))
            change_rate = float(str(stock.get('change_rate', '0')).replace('%', ''))
            
            # Foreign Rate Parsing
            fr_str = str(stock.get('foreign_rate', '0')).replace('%', '')
            foreign_rate = float(fr_str) if fr_str else 0.0
            
            pfr_str = str(stock.get('prev_foreign_rate', '0')).replace('%', '')
            prev_foreign_rate = float(pfr_str) if pfr_str else 0.0
            
            consecutive = int(stock.get('consecutive_days', 0))
            posts_count = int(stock.get('recent_posts_count', 0))
            
            # Volume Check (Simple heuristic if avg unavailable)
            # If 'volume' is a raw number.
            volume = float(stock.get('volume', 0))

            # Logic Reinforcement
            
            # 1. BUY_STRONG: Proven Trend + Institutional/Foreign Interest
            # - Consecutive 3+ days
            # - Foreign ownership increasing
            # - Positive price action
            # - High Community Interest (At least meeting the dashboard threshold)
            if consecutive >= 3 and foreign_rate > prev_foreign_rate and change_rate > 0 and posts_count >= threshold:
                signal = "BUY_STRONG"
                reason = f"3일 연속+외인확대({foreign_rate}%)+Buzz({posts_count})"

            # 2. BUY: Volume Breakout or Sudden Spike
            elif change_rate >= 15.0:
                 signal = "BUY"
                 reason = f"급등세 포착 (+{change_rate}%)"
            elif change_rate > 5.0 and foreign_rate > prev_foreign_rate + 0.1 and posts_count >= (threshold * 1.5):
                 signal = "BUY"
                 reason = f"상승세+외인수급+강한토론({posts_count})"

            # 3. SELL: Foreign Exodus or Trend Break
            elif foreign_rate < prev_foreign_rate - 0.5:
                signal = "SELL"
                reason = f"외인 대량 이탈 ({prev_foreign_rate}% -> {foreign_rate}%)"
            elif change_rate < -5.0 and foreign_rate < prev_foreign_rate and posts_count >= threshold:
                signal = "SELL"
                reason = f"하락세 전환 + 외인 매도 동반"

        except Exception as e:
            # print(f"Sentinel Analysis Error for {stock.get('name')}: {e}")
            pass

        return signal, reason

class GeminiAgent:
    """
    AI Insight Agent using Google Gemini Model.
    Target: gemini-2.5-flash-lite
    """
    def __init__(self):
        self.api_key = os.environ.get('GOOGLE_API_KEY')
        if not self.api_key:
            print("[GeminiAgent] Warning: GOOGLE_API_KEY not found.")
            self.model = None
            return

        genai.configure(api_key=self.api_key)
        # Using the specific model ID requested by verification
        self.model = genai.GenerativeModel('gemini-2.5-flash-lite')

    def generate_risk_assessment(self, symbol, signal_type, technical_reason, keywords, summary):
        """Generates a short risk assessment for SELL signals."""
        if not self.model: return "AI Not Configured"

        prompt = f"""
        Analyze the SELL signal for stock '{symbol}'.
        Signal: {signal_type}
        Reason: {technical_reason}
        Recent Buzz Keywords: {keywords}
        Community Summary: {summary}

        Provide a 1-sentence risk assessment relative to the sell signal.
        Start with "Gemini 2.5 Opinion: "
        """
        try:
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"Analysis Failed: {str(e)}"

    def generate_trading_guide(self, all_data, sentinel_signals=None):
        """
        Generates a comprehensive trading guide.
        Integrates Sentinel-V signals if provided.
        """
        if not self.model: return "AI Not Configured"

        # 1. Prepare Market Data Summary
        sorted_stocks = sorted(all_data, key=lambda x: float(str(x.get('change_rate','0')).replace('%','')), reverse=True)[:10]
        market_context = ""
        for s in sorted_stocks:
            market_context += f"- {s.get('name')}: {s.get('price')} ({s.get('change_rate')}), Keywords: {s.get('top_keywords')}"

        # 2. Sentinel Signals Context
        signal_context = ""
        if sentinel_signals:
            signal_context = "[Sentinel-V Detected Signals]"
            for s in sentinel_signals:
                signal_context += f"- {s['name']}: {s['signal']} ({s['reason']})"
        
        # 3. Load Research/News Data
        research_context = ""
        try:
            if os.path.exists('data/latest_research.json'):
                with open('data/latest_research.json', 'r', encoding='utf-8') as f:
                    research_data = json.load(f)
                    items = research_data.get('company', {}).get('items', [])[:5] + research_data.get('invest', {}).get('items', [])[:3]
                    for item in items:
                        research_context += f"- [Report] {item.get('title')} (Date: {item.get('date')}) -> Trend: {item.get('body_summary', '')[:50]}..."
        except:
            pass

        # 4. Construct Prompt
        prompt = f"""
        Role: Senior Stock Analyst (using Gemini 2.5 Flash Lite)
        Task: Write a concise "Trading Guide" (매매 가이드).
        
        Data Sources:
        {market_context}
        
        {signal_context}
        
        [Recent Reports]
        {research_context}
        
        Requirements:
        1. **Signal Validation**: If there are Sentinel-V signals, explicitly analyze them. Agree or Disagree based on favorable/unfavorable news or buzz.
        2. **Top Picks**: Select 3 stocks (prioritize those with Sentinel Buy signals OR strong News support).
        3. Format:
           📌 **[Stock Name]** | Action: [Buy/Hold/Watch]
           → 💡 Basis: [Technical + Sentinel Signal + News]. *Cite sources.*
           → 🎯 Strategy: [Entry/Exit suggestion]
        
        4. Tone: Professional, objective, and actionable.
        5. Language: Korean.
        """
        
        try:
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"Trading Guide Generation Failed: {str(e)}"



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
        cleaned = re.sub(r'[^가-힣a-zA-Z0-9\s]', ' ', title)
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
                    
                    # 전일 종가 파싱 (리스트에 '전일비' 컬럼이 있음[3], 등락폭임. )
                    # 거래상위 리스트 컬럼: 순위, 종목명, 현재가[2], 전일비[3], 등락률[4], 거래량[5], 거래대금[6], 매수호가[7], 매도호가[8], 시가총액[9], PER[10], ROE[11] ... 
                    # 외국인비율은 기본 컬럼에 없을 수 있음 -> 상세 페이지 파싱 필요
                    
                    # 일단 리스트에서 최대한 확보
                    change_amount_str = cols[3].get_text(strip=True).replace(',', '')
                    # 상승/하락 이미지 또는 클래스 확인이 필요하나, 일단 절대값으로 가져오는 경우가 많음.
                    # 등락률 부호를 보고 전일 종가 역산이 더 정확할 수 있음.
                    # 전일종가 = 현재가 / (1 + 등락률/100)
                    
                    prev_close = 0
                    try:
                        rate_float = float(change_rate.replace('%', ''))
                        prev_close = int(current_price / (1 + rate_float/100))
                    except:
                        pass
                    
                    # 외국인 비율은 보통 리스트 맨 뒤쪽에 있을 수도 있음 (설정 따라 다름)
                    # 여기서는 상세 페이지에서 가져오는 것을 원칙으로 함 (사용자 요청사항 준수)

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
    일별 시세 페이지(sise_day.naver)를 활용합니다.
    """
    url = f"https://finance.naver.com/item/sise_day.naver?code={code}"
    try:
        response = requests.get(url)
        # response.raise_for_status() # 가끔 403 뜰 수 있으니 주의. 헤더 추가 권장.
        
        # 헤더가 없으면 차단될 수 있음
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 일별 시세 테이블 (type2)
        table = soup.select_one('table.type2')
        if not table:
            return {}
            
        # 데이터 행(tr) 추출 (onmouseover 속성 있는 행들이 데이터 행임)
        rows = table.find_all('tr', {'onmouseover': True})
        
        details = {}
        
        # 오늘(최신) 데이터: rows[0]
        if len(rows) > 0:
            cols_today = rows[0].select('td')
            # 컬럼 인덱스(추정): 날짜(0), 종가(1), 전일비(2), 시가(3), 고가(4), 저가(5), 거래량(6)
            # 그런데 외국인 비율은 sise_day에 없음. -> 아뿔싸. 
            # sise_day에는 가격 정보만 있고 외국인 지분율은 없음.
            # 외국인 지분율 이력은 'frgn_man.naver' (투자자별 매매동향) 에 있음? 아님 'sise_day' 말고 다른 페이지?
            # 네이버 금융 -> 시세 -> 일별시세 페이지에는 외국인 소진율이 없음.
            # "종합정보 > 투자자별 매매동향 > 외국인 보유율" 탭이 따로 있음. 
            pass

    except Exception as e:
        pass
        
    # 다시 계획 수정: 
    # 1. 현재 외국인 비율 -> main.naver에서 가져옴 (이미 구현됨)
    # 2. 어제 외국인 비율 -> frgn_man.naver (투자자별 매매동향) 페이지 파싱 필요.
    
    # frgn_man.naver URL: https://finance.naver.com/item/frgn.naver?code={code}
    url_frgn = f"https://finance.naver.com/item/frgn.naver?code={code}"
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url_frgn, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # '보유율' 텍스트 포함된 테이블 찾기
        tables = soup.select('table')
        target_table = None
        
        for t in tables:
            if '외국인' in t.get_text() and '보유율' in t.get_text():
                target_table = t
                break
        
        if target_table:
            # 헤더 제외, 데이터 행 찾기
            # 구조: 
            # Row 0: Header
            # Row 1: Sub-Header
            # Row 2: Spacer (empty)
            # Row 3: Data (Real Today)
            # 하지만 장중/장마감에 따라 행 개수 다를 수 있음. 
            # 간단히 tr을 모두 가져와서 td 개수가 많은 행을 데이터로 간주
            
            rows = target_table.select('tr')
            data_rows = []
            for row in rows:
                cols = row.select('td')
                if len(cols) > 5: # 데이터 행은 최소 6개 이상 컬럼
                    data_rows.append(row)
            
            # 오늘(0), 어제(1)
            if len(data_rows) >= 2:
                cols_today = data_rows[0].select('td')
                cols_yest = data_rows[1].select('td')
                
                if len(cols_today) > 0:
                    details['foreign_rate'] = cols_today[-1].get_text(strip=True)
                
                if len(cols_yest) > 0:
                     details['prev_foreign_rate'] = cols_yest[-1].get_text(strip=True)
                     
                     # 어제 종가 (인덱스 1)
                     prev_close_str = cols_yest[1].get_text(strip=True).replace(',', '')
                     if prev_close_str.isdigit():
                        details['prev_close'] = int(prev_close_str)
        
    except Exception as e:
        print(f"Error fetching foreign details for {code}: {e}")
        
    return details




def get_discussion_stats(code):
    """
    특정 종목 토론실의 게시글 정보를 분석합니다.
    - 당일 00:01 이후 게시글 정밀 카운팅
    - 최대 800개 제한
    """
    
    # 기준 시간 설정 (사용자 요청 V7.4: 당일 08:00 이후)
    now = datetime.now()
    target_time = now.replace(hour=8, minute=0, second=0, microsecond=0)
    
    if now < target_time:
        pass 

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    collected_posts = []
    page = 1
    max_pages = 50 # v7.0 Tuning: Limit to ~1000 posts (User Request: 800)
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
            if not table:
                break
                
            rows = table.select('tr')
            if not rows: 
                break
                
            # Max 800 check (User Request)
            if len(collected_posts) >= 800:
                stop_collecting = True
                break
                
            found_post_in_page = False
            
            for row in rows:
                cols = row.select('td')
                if len(cols) < 5:
                    continue
                
                try:
                    # 날짜 확인 "2024.05.21 14:30"
                    date_text = cols[0].get_text(strip=True)
                    
                    try:
                        post_date = datetime.strptime(date_text, "%Y.%m.%d %H:%M")
                    except ValueError:
                        continue
                        
                    found_post_in_page = True

                    # 기준 시간 체크
                    if post_date < target_time:
                        stop_collecting = True
                        break # 과거 글
                    
                    # 수집 대상
                    title = ""
                    title_tag = row.select_one('a.title')
                    if not title_tag and len(cols) > 1:
                        title_tag = cols[1].select_one('a')
                    
                    if title_tag:
                         title = title_tag.get_text(strip=True)
                    
                    views = cols[3].get_text(strip=True)

                    collected_posts.append({
                        'title': title,
                        'date': date_text,
                        'views': views,
                        'likes': cols[4].get_text(strip=True) if len(cols) > 4 else '0',
                        'dislikes': cols[5].get_text(strip=True) if len(cols) > 5 else '0',
                        'link': title_tag['href'] if title_tag else ""
                    })
                    
                except Exception:
                    continue
            
            page += 1
            
        except Exception as e:
            print(f"Error fetching page {page} for {code}: {e}")
            break
            
    # Sort by Likes (Recomm) initially to pick candidates for Deep Dive
    collected_posts.sort(key=lambda x: int(x['likes']) if str(x['likes']).isdigit() else 0, reverse=True)

    return {
        'code': code,
        'recent_posts_count': len(collected_posts),
        'latest_posts': collected_posts, # Return ALL collected (will filter top 10 in main)
        'all_posts_titles': [p['title'] for p in collected_posts] 
    }

def fetch_post_body(link_suffix):
    """
    게시글 본문을 가져옵니다. (Deep Dive Analysis)
    link_suffix: /item/board_read.naver?code=...&nid=...
    """
    try:
        url = f"https://finance.naver.com{link_suffix}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://finance.naver.com/'
        }
        # Random sleep to be polite/safe
        time.sleep(0.3) 
        
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Naver Finance Board Body Selector
        # specific ID or class might vary, usually 'div#body' or 'div.view_se'
        body_tag = soup.select_one('#body') or soup.select_one('.view_se') or soup.select_one('.scr01')
        return ""
    except Exception:
        return ""


import analyzer
from src import research_scraper
from src.features.gemini_agent import GeminiAgent  # [NEW] Import Gemini Agent
# from src import utils # Removed V7.0 (Legacy)

def load_env_manual(filepath=".env.local"):
    # Local .env support
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    key, val = line.strip().split('=', 1)
                    os.environ[key] = val.strip().strip('"').strip("'")

# --- Helper Functions (Added for V6.7 Fix) ---
def get_current_kst_time():
    """Returns current time in KST (UTC+9)."""
    # UTC time from GitHub Actions (or local system)
    now_utc = datetime.utcnow()
    now_kst = now_utc + timedelta(hours=9)
    return now_kst

def get_threshold_by_time(hour):
    """Returns the comment count threshold based on the hour (KST)."""
    # 10:00 run (covers 09:00 ~ 10:XX) -> Threshold 40 (Stricter)
    if 9 <= hour < 12:
        return 40
    # 13:00 run (covers 09:00 ~ 13:XX) -> Threshold 60
    elif 12 <= hour < 14:
        return 60
    # 15:00 run (covers 09:00 ~ 15:XX) -> Threshold 100
    elif 14 <= hour < 24:
        return 100
    return 10 # Default fallback

def get_yesterday_last_stocks():
    """
    reports.json을 분석하여 '어제' 날짜 중 가장 마지막 스냅샷(또는 리포트)의 종목 코드를 가져옵니다.
    """
    try:
        reports_file = 'data/reports.json'
        if not os.path.exists(reports_file):
            return set()

        import json
        with open(reports_file, 'r', encoding='utf-8') as f:
            reports = json.load(f)
        
        # 오늘 날짜 (KST 기준)
        now_kst = get_current_kst_time()
        today_str = now_kst.strftime('%Y-%m-%d')
        
        # 어제 날짜
        yesterday = now_kst - timedelta(days=1)
        yesterday_str = yesterday.strftime('%Y-%m-%d')
        
        # 1. reports.json에서 어제 날짜인 것들 필터링
        # report['date'] 형식: "2024-05-21 15:00"
        yesterday_reports = [
            r for r in reports 
            if r['date'].startswith(yesterday_str)
        ]
        
        if not yesterday_reports:
            # 어제 리포트가 없다면, 그 전이라도 가져와야 하나? 
            # 사용자 요청: "어제 수집한 가장 마지막 데이터"
            # 어제가 휴일일 수 있음 -> 주말/휴일 제외 로직이 있다면 데이터가 없을 수 있음.
            # 일단 '어제'가 캘린더상 어제인지, 직전 영업일인지 모호하나 "어제"로 구현.
            # 직전 영업일로 하려면 복잡해짐. 일단 캘린더 어제로 시도.
            return set()
            
        # 2. 개중 가장 마지막 것 (reports.json은 최신순 정렬되어 있다고 가정, 혹은 timestamp 확인)
        # reports.json은 insert(0, entry) 하므로 0번 인덱스가 최신.
        # yesterday_reports도 순서 유지된다면 0번이 가장 늦은 시간.
        last_report = yesterday_reports[0]
        filename = last_report['filename'] # trending_integrated_20240520_150000.xlsx
        
        # 3. 파일 로드 (Excel)
        file_path = f"data/{filename}" # analyzer.save_data saves to current dir, usually root or relative?
        # scraper.py 실행 위치 기준. saved_files['excel']은 보통 상대경로(파일명)만 리턴함 (analyzer.py 확인 필요)
        # analyzer.save_data: xlsx_filename = f"{base_name}.xlsx" -> 현재 디렉토리.
        
        if not os.path.exists(filename):
            # 혹시 data/ 폴더 안에 있을 수도? (코드는 현재 디렉토리에 저장함)
            # scraper.py: saved_files = analyzer.save_data(...) -> saved_files['excel'] returns filename.
            pass
            
        import pandas as pd
        if filename.endswith('.xlsx'):
            df = pd.read_excel(filename)
        elif filename.endswith('.csv'):
            df = pd.read_csv(filename)
        else:
            return set()
            
        # 'code' or '종목코드' 컬럼 추출
        # analyzer.py result_df_kr 컬럼: '종목코드'
        if '종목코드' in df.columns:
            return set(df['종목코드'].astype(str).str.zfill(6).tolist())
        
        return set()
        
    except Exception as e:
        print(f"[Warning] Failed to get yesterday's stocks: {e}")
        return set()

def append_to_monthly_report(df_kr, now_kst):
    """
    현재 월의 누적 리포트에 데이터를 추가합니다.
    
    Args:
        df_kr: 한글 결과 DataFrame
        now_kst: 현재 KST 시간
    
    Returns:
        monthly_file_path: 저장된 월별 파일 경로
        total_count: 누적된 총 행 개수
    """
    try:
        # 1. 월별 파일명 생성
        month_str = now_kst.strftime('%Y-%m')
        monthly_filename = f'monthly_report_{month_str}.xlsx'
        monthly_filepath = f'data/{monthly_filename}'
        
        # 2. 현재 데이터에 날짜/시간 컬럼 추가
        df_with_datetime = df_kr.copy()
        df_with_datetime.insert(0, '취합시간', now_kst.strftime('%H:%M'))
        df_with_datetime.insert(0, '취합날짜', now_kst.strftime('%Y-%m-%d'))
        
        # 3. 기존 파일 로드 또는 새로 생성
        if os.path.exists(monthly_filepath):
            # 기존 데이터 로드
            existing_df = pd.read_excel(monthly_filepath, engine='openpyxl')
            
            # [Duplicate Check] 같은 날짜 + 같은 시간대(HH) 데이터가 있으면 삭제 (덮어쓰기 모드)
            # 이유: Tasker와 GitHub Cron이 중복 실행되거나 재실행 시 데이터 중복 방지
            try:
                current_date = now_kst.strftime('%Y-%m-%d')
                current_hour = now_kst.strftime('%H')
                
                # 취합시간(HH:MM)에서 HH 추출하여 비교
                # 포맷이 확실하다고 가정 (문자열 '10:00')
                mask = (existing_df['취합날짜'] == current_date) & \
                       (existing_df['취합시간'].astype(str).str.startswith(current_hour))
                
                if mask.any():
                    deleted_count = mask.sum()
                    print(f"[Monthly Report] Overwriting {deleted_count} existing rows for {current_date} {current_hour}h...")
                    existing_df = existing_df[~mask]
            except Exception as e:
                print(f"[Warning] Duplicate check failed: {e}")

            # [Duplicate Check] 같은 날짜 + 같은 시간대(HH) 데이터가 있으면 삭제 (덮어쓰기 모드)
            try:
                current_date = now_kst.strftime('%Y-%m-%d')
                current_hour = now_kst.strftime('%H')
                
                # 취합시간(HH:MM) 포맷 가정
                mask = (existing_df['취합날짜'] == current_date) & \
                       (existing_df['취합시간'].astype(str).str.startswith(current_hour))
                
                if mask.any():
                    deleted_count = mask.sum()
                    print(f"[Monthly Report] Overwriting {deleted_count} existing rows for {current_date} {current_hour}h...")
                    existing_df = existing_df[~mask]
            except Exception as e:
                print(f"[Warning] Duplicate check failed: {e}")

            # 새 데이터 추가
            combined_df = pd.concat([existing_df, df_with_datetime], ignore_index=True)
            print(f"[Monthly Report] Appended {len(df_with_datetime)} rows to existing file (Total: {len(combined_df)} rows)")
        else:
            # 새 파일 생성
            combined_df = df_with_datetime
            print(f"[Monthly Report] Created new monthly report with {len(combined_df)} rows")
        
        # 4. 파일 저장
        os.makedirs('data', exist_ok=True)
        combined_df.to_excel(monthly_filepath, index=False, engine='openpyxl')
        
        return monthly_filepath, len(combined_df)
        
    except Exception as e:
        print(f"[Error] Failed to update monthly report: {e}")
        return None, 0

if __name__ == "__main__":
    # 0. Load Environment Variables
    load_env_manual()
    
    # 1. Initialize Time & Threshold (CRITICAL FIX V6.7)
    now_kst = get_current_kst_time()
    current_hour = now_kst.hour
    threshold = get_threshold_by_time(current_hour)
    
    now = now_kst # Sync variable name for later use
    
    print(f"[System] Time (KST): {now_kst.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # --- Market Holiday Check (V6.8) ---
    import holidays
    kr_holidays = holidays.KR()
    
    is_weekend = now_kst.weekday() >= 5 # 5=Sat, 6=Sun
    is_holiday = now_kst.strftime('%Y-%m-%d') in kr_holidays
    
    if is_weekend or is_holiday:
        reason = "Weekend" if is_weekend else f"Holiday ({kr_holidays.get(now_kst.strftime('%Y-%m-%d'))})"
        print(f"[System] Market Closed Today ({reason}). Skipping execution.")
        sys.exit(0) # Exit cleanly, no Telegram sent.
        
    print(f"[System] Threshold determined: {threshold} posts (based on hour {current_hour})")

    # --- 0. Initialize Telegram Manager (V7.0) ---
    try:
        from src.telegram_manager import TelegramManager
        tg_manager = TelegramManager()
        # Dashboard Link moved to end
    except Exception as e:
        print(f"[System] Failed to initialize TelegramManager: {e}")
        tg_manager = None
    # 2. Research Briefing (Enabled)
    # --- 0. Research Report Scraping (Disabled V8.0) ---
    print("\n[Research] Research Report Scraping is DISABLED (V8.0).")
    # try:
    #     research_scraper.main()
    #     print("=== [Phase 0] Research Scraping Complete ===")
    # except Exception as e:
    #     print(f"=== [Phase 0] Research Scraping Failed: {e} ===")

    # [Note] Legacy Telegram Notification for Research also disabled.

    all_data = [] # 통합 데이터 저장용

    # [Consolidated Scraping V8.0]
    # Fetch Volume Top 30 + Rising Top 20
    candidates = []
    markets = ['KOSPI', 'KOSDAQ']  # [FIX] Define markets
    
    for market in markets:
        # 1. Volume Top 30
        vol_stocks = get_top_trending_stocks(market)
        for s in vol_stocks: s['source'] = 'volume'
        candidates.extend(vol_stocks)
        
        # 2. Rising Top 20
        rise_stocks = get_top_rising_stocks(market)
        candidates.extend(rise_stocks)
    
    # Deduplicate by Code
    unique_candidates = {}
    for stock in candidates:
        if stock['code'] not in unique_candidates:
            unique_candidates[stock['code']] = stock
        else:
            # If already exists, maybe update source info to 'both'?
            pass
            
    print(f"\n[System] Total Unique Candidates: {len(unique_candidates)}")

    # Process Candidates
    today_consecutive_check_done = False
    yesterday_codes = set()
    
    # [Consecutive Check V7.4]
    try:
        yesterday_codes = get_yesterday_last_stocks()
    except:
        pass

    count_collected = 0
    
    print("\n[System] Starting detailed analysis & filtering...")
    
    # [Parallel Processing V8.6]
    import concurrent.futures

    def process_single_stock(stock, yesterday_codes, threshold):
        """
        Process a single stock: fetch details, stats, discussion bodies, and apply logic.
        Returns the updated stock dict if it meets criteria, else None.
        """
        try:
            # 1. 상세 정보 (전일종가, 외국인)
            details = get_stock_details(stock['code'])
            stock.update(details)
            
            # [Added V8.X] Foreign Change Rate
            try:
                fr = float(str(stock.get('foreign_rate', '0')).replace('%', '').strip())
                pfr = float(str(stock.get('prev_foreign_rate', '0')).replace('%', '').strip())
                stock['foreign_change_rate'] = round(fr - pfr, 2)
            except:
                stock['foreign_change_rate'] = 0.0

            # [Added V8.2] Version
            stock['scraper_version'] = SCRAPER_VERSION

            # [Added V8.2] Version
            stock['scraper_version'] = SCRAPER_VERSION
            
            # 2. 토론방 정보 (시간 기준 카운팅)
            stats = get_discussion_stats(stock['code'])
            recent_count = stats.get('recent_posts_count', 0)
            
            # FILTER HERE
            if recent_count >= threshold:
                stock['recent_posts_count'] = recent_count
                
                # [Deep Dive V7.5] Analyze Top 10 Liked Posts
                raw_latest = stats.get('latest_posts', [])
                raw_latest.sort(key=lambda x: int(x['likes']) if str(x['likes']).isdigit() else 0, reverse=True)
                candidates_posts = raw_latest[:10] # Renamed from 'candidates' to avoid confusion
                
                print(f"   [dtl] {stock['name']}: {recent_count} (Fetching bodies...)")
                for post in candidates_posts:
                    if post.get('link'):
                        post['body'] = fetch_post_body(post['link'])
                    else:
                        post['body'] = ""
                
                stock['latest_posts'] = candidates_posts
                stock['all_posts_titles'] = stats.get('all_posts_titles', []) 
                
                # Keywords (for Sentinel-V) - Extract meaningful keywords, not raw titles
                titles = [p['title'] for p in candidates_posts]
                meaningful_kws = extract_meaningful_keywords(titles, stock.get('name', ''))
                stock['top_keywords'] = ", ".join(meaningful_kws) if meaningful_kws else ""

                # Consecutive Flag
                if stock['code'] in yesterday_codes:
                    stock['is_consecutive'] = True
                else:
                    stock['is_consecutive'] = False

                return stock
            else:
                return None

        except Exception as e:
            print(f"Error processing {stock['name']}: {e}")
            return None

    # Use ThreadPoolExecutor for Parallel Scraping
    print(f"\n[System] Starting detailed analysis with Parallel Processing (Workers: 4)...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        # Prepare arguments for map/submit
        # We need to pass stock, yesterday_codes, and threshold to each call
        future_to_stock = {
            executor.submit(process_single_stock, stock, yesterday_codes, threshold): stock 
            for stock in unique_candidates.values()
        }
        
        for future in concurrent.futures.as_completed(future_to_stock):
            stock_ref = future_to_stock[future]
            try:
                result = future.result()
                if result:
                    all_data.append(result)
                    count_collected += 1
            except Exception as exc:
                print(f"{stock_ref['name']} generated an exception: {exc}")

    print(f"\n[System] Final Collected Items: {len(all_data)}")
    # --- Consolidated Analysis & Notification (V8.0) ---
    try:
        from src.telegram_manager import TelegramManager
        # from src.features.sentinel_v import SentinelV  <-- REMOVED (Inlined)
        # from src.features.gemini_agent import GeminiAgent <-- REMOVED (Inlined)
        
        try:
            tg_manager = TelegramManager()
        except:
            tg_manager = None
            
        import json
        os.makedirs('data', exist_ok=True)
        
        if all_data:
            print(f"\nAnalyzing total {len(all_data)} items...")

            # [Consecutive Days Calculation - Unlimited]
            all_codes = [s['code'] for s in all_data]
            consecutive_map = calculate_long_term_consecutive_days(all_codes)
            for s in all_data:
                s['consecutive_days'] = consecutive_map.get(s['code'], 1)
                s['연속_등록'] = s['consecutive_days'] > 1 # Maintain legacy bool for fallback

            result_df_kr, result_df_en = analyzer.analyze_discussion_trend(all_data)
            result_df_en = result_df_en.where(pd.notnull(result_df_en), None)
            json_records = result_df_en.to_dict('records')

            # [Feature: 5-Day Cumulative Analysis]
            extra_sheets = {}
            try:
                from src import analyzer_5days
                df_5days = analyzer_5days.analyze_5days()
                if not df_5days.empty:
                    df_5days = df_5days.where(pd.notnull(df_5days), None)
                    with open('data/analysis_5days.json', 'w', encoding='utf-8') as f:
                        f.write(df_5days.to_json(orient='records', force_ascii=False))
                    extra_sheets['5Day_Analysis'] = df_5days
            except Exception as e:
                print(f"[Warning] 5-Day Analysis Failed: {e}")

            # [Feature: 3-Day Cumulative Analysis]
            try:
                df_3days = analyzer_5days.analyze_3days()
                if not df_3days.empty:
                    df_3days = df_3days.where(pd.notnull(df_3days), None)
                    with open('data/analysis_3days.json', 'w', encoding='utf-8') as f:
                        f.write(df_3days.to_json(orient='records', force_ascii=False))
                    extra_sheets['3Day_Analysis'] = df_3days
            except Exception as e:
                print(f"[Warning] 3-Day Analysis Failed: {e}")
            
            # Save CSV & Excel
            filename_prefix = f"trending_integrated"
            # [User Request] Revert to Korean Format (Original) - Dashboard expects Korean keys!
            saved_files = analyzer.save_data(result_df_kr, filename_prefix=filename_prefix, extra_sheets=extra_sheets)
            
            # --- Fix: Save JSON for Frontend (Dashboard) ---
            try:
                # Helper function to sanitize NaN values for JSON
                import math
                def sanitize_for_json(obj):
                    """Recursively replace NaN and Infinity with None/0 for valid JSON"""
                    if isinstance(obj, dict):
                        return {k: sanitize_for_json(v) for k, v in obj.items()}
                    elif isinstance(obj, list):
                        return [sanitize_for_json(item) for item in obj]
                    
                    # Handle Numeric NaNs
                    if isinstance(obj, float):
                        if math.isnan(obj) or math.isinf(obj):
                            return 0 # Default to 0 instead of None for easier frontend math
                    if pd.isna(obj): 
                        return 0
                        
                    return obj
                
                # Sanitize json_records before saving
                clean_json_records = sanitize_for_json(json_records)

            except Exception as e:
                print(f"[Warning] JSON Sanitization failed: {e}")
                clean_json_records = json_records # Fallback

    # ... [Skipping unchanged lines] ...

            # monthly report
            # [User Request] Use Korean Data
            monthly_file, monthly_count = append_to_monthly_report(result_df_kr, now_kst)
            
            # reports.json update
            if 'excel' in saved_files:
                reports_file = 'data/reports.json'
                current_reports = []
                if os.path.exists(reports_file):
                    try:
                        with open(reports_file, 'r', encoding='utf-8') as f:
                            current_reports = json.load(f)
                    except: pass
                
                if monthly_file:
                    month_str = now_kst.strftime('%Y-%m')
                    month_label = f"{now_kst.month}월 누적 리포트 ({month_str})"
                    monthly_entry = { "type": "monthly", "date": month_str, "filename": os.path.basename(monthly_file), "count": monthly_count, "label": month_label, "timestamp": datetime.now().timestamp() }
                    
                    monthly_exists = False
                    for i, report in enumerate(current_reports):
                        if report.get('type') == 'monthly' and report.get('date') == month_str:
                            current_reports[i] = monthly_entry
                            monthly_exists = True
                            break
                    if not monthly_exists:
                        daily_start = next((i for i, r in enumerate(current_reports) if r.get('type') == 'daily'), len(current_reports))
                        current_reports.insert(daily_start, monthly_entry)
                
                daily_entry = { "type": "daily", "date": now_kst.strftime('%Y-%m-%d %H:%M'), "filename": os.path.basename(saved_files['excel']), "count": len(all_data), "timestamp": datetime.now().timestamp() }
                daily_start = next((i for i, r in enumerate(current_reports) if r.get('type') == 'daily'), len(current_reports))
                current_reports.insert(daily_start, daily_entry)
                
                daily_reports = [r for r in current_reports if r.get('type') == 'daily'][:50]
                monthly_reports = [r for r in current_reports if r.get('type') == 'monthly']
                monthly_reports.sort(key=lambda x: x.get('date', ''), reverse=True)
                current_reports = monthly_reports + daily_reports
                
                with open(reports_file, 'w', encoding='utf-8') as f:
                    json.dump(current_reports, f, ensure_ascii=False, indent=2)

        # Save latest_stocks.json
        with open('data/latest_stocks.json', 'w', encoding='utf-8') as f:
            json.dump(json_records, f, ensure_ascii=False, indent=2)

        # Save Time Snapshot
        snapshot_name = None
        if 9 <= current_hour <= 10: snapshot_name = "stocks_1000.json"
        elif 12 <= current_hour <= 13: snapshot_name = "stocks_1300.json"
        elif 14 <= current_hour <= 23: snapshot_name = "stocks_1500.json"
        
        if snapshot_name:
            with open(f'data/{snapshot_name}', 'w', encoding='utf-8') as f:
                json.dump(json_records, f, ensure_ascii=False, indent=2)

        # --- Consolidated Notification ---
        if all_data and tg_manager:
            try:
                print("[System] Generating Consolidated Telegram Report...")
                
                # 1. KOSPI Report
                records = result_df_kr.to_dict('records')
                kospi_items = [r for r in records if r.get('시장구분') == 'KOSPI']
                if kospi_items:
                    # Header Style: [KOSPI] Top 5 (토론 급등) (v7.0)
                    kospi_msg = f"📉 <b>[KOSPI] Top {min(len(kospi_items), 5)} (토론 급등)</b>\n\n"
                    for item in kospi_items[:5]: # Show Top 5
                        name = item['종목명']
                        # Price/Change might be int or str, handle safely
                        try:
                            price = f"{int(item.get('현재가', 0)):,}"
                        except:
                            price = item.get('현재가', '0')
                            
                        change = item['등락률']
                        posts = item['당일_게시글수']
                        summary = item.get('게시물_요약', '요약 없음')
                        
                        kospi_msg += f"🔥 <b>{name}</b> ({price}원 | {change})\n"
                        kospi_msg += f"💬 {posts}개 의견\n"
                        kospi_msg += f"📝 {summary}\n\n"
                        
                    if len(kospi_items) > 5: kospi_msg += f"<i>... and {len(kospi_items)-5} more on Dashboard</i>\n"
                    tg_manager.send_message(kospi_msg)

                # 2. KOSDAQ Report
                kosdaq_items = [r for r in records if r.get('시장구분') == 'KOSDAQ']
                if kosdaq_items:
                    kosdaq_msg = f"📈 <b>[KOSDAQ] Top {min(len(kosdaq_items), 5)} (토론 급등)</b>\n\n"
                    for item in kosdaq_items[:5]: # Show Top 5
                        name = item['종목명']
                        try:
                            price = f"{int(item.get('현재가', 0)):,}"
                        except:
                            price = item.get('현재가', '0')
                            
                        change = item['등락률']
                        posts = item['당일_게시글수']
                        summary = item.get('게시물_요약', '요약 없음')
                        
                        kosdaq_msg += f"🔥 <b>{name}</b> ({price}원 | {change})\n"
                        kosdaq_msg += f"💬 {posts}개 의견\n"
                        kosdaq_msg += f"📝 {summary}\n\n"

                    if len(kosdaq_items) > 5: kosdaq_msg += f"<i>... and {len(kosdaq_items)-5} more on Dashboard</i>\n"
                    tg_manager.send_message(kosdaq_msg)

                # 3. Sentinel-V Signals (Integrated)
                sentinel = SentinelV()
                buy_signals = []
                sell_signals = []
                
                sentinel_data = [] # For Gemini Integration
                
                # [DEBUG] Check SentinelV Origin
                import inspect
                print(f"[DEBUG] SentinelV Class: {SentinelV}")
                try:
                    print(f"[DEBUG] SentinelV File: {inspect.getfile(SentinelV)}")
                    print(f"[DEBUG] analyze_stock signature: {inspect.signature(SentinelV.analyze_stock)}")
                except Exception as e:
                    print(f"[DEBUG] Inspection failed: {e}")
                
                # Re-analyze all data for signals
                for stock in all_data:
                    signal, reason = sentinel.analyze_stock(stock, threshold=threshold)
                    if "BUY" in signal:
                        buy_signals.append(f"🔴 <b>매수 신호</b>: {stock['name']} ({signal})\n   └ <i>{reason}</i>")
                        sentinel_data.append({'name': stock['name'], 'signal': signal, 'reason': reason})
                    elif "SELL" in signal:
                        # [V8.1] Expert Opinion Injection
                        try:
                            summary = stock.get('posts_summary', '요약 없음')
                            keywords = stock.get('top_keywords', '키워드 없음')
                            ai_opinion = gemini.generate_risk_assessment(
                                symbol=stock['name'],
                                signal_type=signal,
                                technical_reason=reason,
                                keywords=keywords,
                                summary=summary
                            )
                            sell_signals.append(f"🔵 <b>매도 신호</b>: {stock['name']} ({signal})\n   └ <i>Reason: {reason}</i>\n   └ 🧠 <b>AI 의견</b>: {ai_opinion}")
                        except Exception as e:
                            print(f"[Warning] AI Opinion Failed: {e}")
                            sell_signals.append(f"🔵 <b>매도 신호</b>: {stock['name']} ({signal})\n   └ <i>{reason}</i>")
                
                if buy_signals or sell_signals:
                    signal_msg = "⚡ <b>[Sentinel-V Signals]</b>\n" + "\n".join(buy_signals + sell_signals)
                    tg_manager.send_message(signal_msg)

                # 4. Expert Guide (Detailed)
                try:
                    gemini = GeminiAgent()
                    if gemini.model:
                        print("[System] Generating Trading Guide...")
                        guide_text = gemini.generate_trading_guide(all_data, sentinel_signals=sentinel_data)
                        
                        # Split guide if too long
                        if len(guide_text) > 3000:
                            parts = [guide_text[i:i+3000] for i in range(0, len(guide_text), 3000)]
                            for i, part in enumerate(parts):
                                tg_manager.send_message(f"🧠 <b>[Expert Guide {i+1}/{len(parts)}]</b>\n{part}")
                        else:
                            tg_manager.send_message(f"🧠 <b>[Expert Guide]</b>\n{guide_text}")
                    else:
                        print("[Warning] Gemini Model not initialized (Check API Key).")
                        tg_manager.send_message("⚠️ <b>[System Warning]</b>\nGemini AI 모델 초기화 실패.\nGitHub Secrets의 <code>GOOGLE_API_KEY</code>를 확인해주세요.")
                except Exception as user_e:
                    print(f"Gemini Error: {user_e}")
                    tg_manager.send_message(f"⚠️ <b>[System Error]</b>\nGemini 가이드 생성 실패: {user_e}")

                # 5. Dashboard Link (Separate small msg)
                dash_msg = f"👉 <b>Dashboard</b>: {os.environ.get('DASHBOARD_URL', 'https://stockbot-phi.vercel.app')}"
                tg_manager.send_message(dash_msg)
                    
            except Exception as e:
                print(f"[ERROR] Notification Logic Failed: {e}")
                
        elif not all_data and tg_manager:
            tg_manager.send_no_data_alert(threshold)

    except Exception as e:
        print(f"Failed in consolidated section: {e}")


    finally:
        # Save Status JSON for Frontend (ALWAYS RUN)
        try:
            import json
            from datetime import timezone, timedelta
            
            # Get current KST time at save point (not script start time)
            kst_tz = timezone(timedelta(hours=9))
            current_kst = datetime.now(kst_tz)
            
            status_data = {
                "last_updated": current_kst.strftime('%Y-%m-%d %H:%M:%S'),
                "message": "Data updated successfully" if all_data else "No data collected",
                "count": len(all_data) if 'all_data' in locals() else 0
            }
            with open('data/status.json', 'w', encoding='utf-8') as f:
                json.dump(status_data, f, ensure_ascii=False, indent=2)
            print(f"[System] status.json updated at {status_data['last_updated']}")
        except Exception as status_e:
            print(f"[ERROR] Failed to save status.json: {status_e}")









