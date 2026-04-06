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
SCRAPER_VERSION = "9.2 (Strategy Advisor)"

# --- Strategy Advisor ---
from src.strategy.advisor import StrategyAdvisor

# --- SentinelV & GeminiAgent (Inlined for Stability) ---
# --- Korean NLP Helpers ---
# Ordered by length (longer first) so longer suffixes match first
KO_PARTICLES = [
    # Multi-char particles first (order matters - longest first)
    '으로부터', '로부터', '으로서', '에서부터', '에서도', '에게서', '에게도',
    '이라는', '라는', '이라고', '라고', '이라며', '라며', '이지만', '지만',
    '이지만도', '인데도', '인데', '이고도', '이고', '이며', '이거나', '거나',
    '이라도', '라도', '에서', '에게', '에도', '에만', '로도', '로만', '으로도',
    '으로만', '으로', '로서', '부터', '까지', '마저', '조차', '이나마', '나마',
    '이나', '나', '이든', '든', '은커녕', '는커녕', '이라면', '라면',
    '들은', '들이', '들의', '들에', '들도', '들만', '들을', '들도',
    '에서', '에게', '한테', '에게서', '한테서',
    '이면', '이면서', '면서', '이지', '이라',
    '하고', '하면', '하지', '하여', '하며', '하니', '하든',
    '같이', '처럼', '보다', '만큼',
    '들', '은', '는', '이', '가', '을', '를', '의', '에', '도', '만', '로', '고',
    '서', '면', '야', '아', '여', '와', '과', '랑',
]

KO_VERB_ENDINGS = [
    # Verb/adjective endings
    '습니다', '입니다', '합니다', '됩니다', '입니다', '겠습니다',
    '했습니다', '았습니다', '었습니다',
    '하는군', '하는구나', '하는데', '하더니', '하다가', '합니다만',
    '한다고', '한다며', '한다고요', '다고요',
    '네요', '군요', '거든요', '더라고요', '더군요', '잖아요',
    '세요', '에요', '아요', '어요', '이에요', '이에요',
    '겠어', '겠지', '겠죠', '것같아', '것같은',
    '하는지', '하는가', '하는가요', '하는지요',
    '하자', '하자마자', '할수록', '할지', '할지도',
    '스럽다', '스러운', '스럽게', '스러워',
    '다며', '다면서', '다고', '다는', '다던', '다더니',
    '지않', '지않는', '지않은', '않는', '않은', '않고', '않아',
    'ㄴ다고', 'ㄴ다며', 'ㄴ다면',
    '했다고', '했다며', '됐다고', '됐다며',
    '다고요', '이라고요', '라고요',
    '더라고', '더군', '더니', '더라',
    '였나', '였는지', '였던',
    '었나', '었는지', '었던',
    '이다', '있다', '없다', '한다', '된다', '된다', '간다', '온다',
    '같다', '같은', '같아', '같이',
    '이다', '이야', '이야기',
    '구나', '군요', '구요',
    '다면', '다고', '다는', '다든',
    '었다', '았다', '겠다',
    '이요', '네', '죠', '죠?', '지요',
    '합니', '하면', '하고', '하니', '하여',
    '만큼', '처럼', '마냥', '같이',
    '때문', '때문에', '탓에', '탓',
    '입니', '이라', '이야', '이지',
    '에서', '에가', '에는',
    '에다', '에다가', '마저', '조차', '까지',
    '이자', '도록', '토록',
    '고도', '고나', '곤', '고는',
    '는데', '은데', '인데', '거든',
    '어야', '아야', '여야',
    '어도', '아도', '여도',
    '는다', '는지', '는가',
    '지만', '지는', '지도', '지가',
    '로다', '으로다',
    '놓고', '두고', '가며',
    '있는', '없는', '있네', '없네', '있어', '없어',
    '있는데', '없는데',
    '다'
]

STOPWORDS = {
    # 대명사 / 지시어
    '오늘', '어제', '내일', '지금', '현재', '이번', '저번', '요즘',
    '여기', '저기', '거기', '이거', '저거', '그거', '이것', '저것', '그것',
    '나', '저', '제가', '내가', '우리', '너', '네가', '그', '그녀', '저희',
    '이분', '저분', '그분', '이사람', '저사람', '그사람',
    # 접속사 / 부사
    '그리고', '그런데', '그래서', '하지만', '그러나', '또한', '또', '다시',
    '먼저', '결국', '즉', '즉시', '바로', '과연', '역시', '아직', '이미',
    '물론', '단지', '단순히', '그냥', '아무', '아무것', '근데', '암튼', '아무튼',
    '잠깐', '잠시', '조금', '좀', '많이', '매우', '너무', '정말', '진짜',
    '진심', '완전', '대박', '와', '헐', '어머', '아이고', '맙소사',
    '솔직히', '사실', '사실은', '그냥', '일단', '우선',
    # 동사/형용사 기본형
    '있다', '없다', '하다', '되다', '이다', '같다', '보다', '주다', '가다', '오다',
    '알다', '모르다', '싶다', '좋다', '나쁘다', '크다', '작다',
    '많다', '적다', '높다', '낮다', '빠르다', '늦다',
    # 조동사류
    '합니다', '입니다', '습니다', '됩니다', '같습니다', '봅니다',
    # 주식/투자 일반 단어
    '주식', '종목', '매수', '매도', '매매', '투자', '주가', '가격',
    '상한가', '하한가', '급등', '급락', '폭등', '폭락', '상승', '하락',
    '정보', '분석', '전망', '예상', '의견', '생각', '질문', '궁금',
    '코스피', '코스닥', 'KOSPI', 'KOSDAQ',
    '공시', '뉴스', '특징주', '단독', '상보', '종합', '속보', '긴급',
    '오후', '오전', '장전', '장후', '시간외', '마감', '시작',
    '원', '만원', '천원', '억', '조', '억원',
    '실시간', '현재가', '목표가', '매수가', '매도가',
    # 요일 / 날짜
    '월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일',
    '월욜', '화욜', '수욜', '목욜', '금욜',
    '오늘도', '어제도', '내일도', '이번주', '다음주', '지난주',
    # 감탄사
    'ㅋㅋ', 'ㅋㅋㅋ', 'ㄷㄷ', 'ㄷㄷㄷ', 'ㅎㅎ', 'ㅎㅎㅎ', 'ㅠㅠ', 'ㅜㅜ',
    # 구어체
    '가자', '가즈아', '살까', '팔까', '롱', '숏', '존버', '물타기', '불타기',
    'ㄹㅇ', 'ㅈㄴ', 'ㅅㅂ', 'ㄱㄴ',
}

def _strip_korean_suffix(word: str) -> str:
    """Strip common Korean particles and verb endings to get the root."""
    # Try verb endings first (longer match wins due to sorted order)
    for ending in sorted(KO_VERB_ENDINGS, key=len, reverse=True):
        if word.endswith(ending) and len(word) > len(ending):
            root = word[:-len(ending)]
            if len(root) >= 1:  # Keep at least 1 char
                return root
    # Then try particles
    for particle in KO_PARTICLES:
        if word.endswith(particle) and len(word) > len(particle):
            root = word[:-len(particle)]
            if len(root) >= 1:
                return root
    return word


def extract_meaningful_keywords(titles, stock_name, max_keywords=5):
    """
    Extracts meaningful Korean keywords from post titles.
    Uses suffix stripping before filtering to handle agglutinative Korean.
    """
    # Build stock name parts to filter out
    name_parts = set()
    if stock_name and len(stock_name) >= 2:
        name_parts.add(stock_name)
        name_parts.add(stock_name[:2])
        if len(stock_name) > 2:
            name_parts.add(stock_name[-2:])
    
    root_freq = {}  # stripped root -> frequency
    root_surface = {}  # stripped root -> best surface form (shortest)

    for title in titles:
        # Keep only Korean + English + numbers, replace everything else with space
        cleaned = re.sub(r'[^가-힣a-zA-Z0-9\s]', ' ', title)
        words = cleaned.split()
        
        for raw_word in words:
            if not raw_word:
                continue
            
            # Step 1: Strip Korean particles/endings to get root
            root = _strip_korean_suffix(raw_word)
            
            # Step 2: Length filter (root must be >= 2 chars)
            if len(root) < 2:
                continue
            
            # Step 3: Digit-only filter
            if root.isdigit():
                continue
            
            # Step 4: Stopword check (both raw and stripped)
            if root in STOPWORDS or raw_word in STOPWORDS:
                continue
            
            # Step 5: Skip single-syllable Korean chars (most are particles/noise)
            # A Korean syllable block is a single char in the range 가-힣
            if len(root) == 1 and '가' <= root <= '힣':
                continue
            
            # Step 6: Stock name filter
            if any(part and part in root for part in name_parts):
                continue
            
            # Step 7: Skip if root still ends with a particle (multi-level)
            # Apply one more pass
            root2 = _strip_korean_suffix(root)
            if root2 != root and len(root2) >= 2:
                root = root2
            
            # Step 8: Final stopword re-check after double stripping
            if root in STOPWORDS:
                continue
            
            # Step 9: Skip common noise patterns
            # e.g., purely repeat chars like ㅋㅋ
            if len(set(root)) == 1:
                continue

            root_freq[root] = root_freq.get(root, 0) + 1
            # Track the shorter surface form (prefer concise display)
            if root not in root_surface or len(raw_word) < len(root_surface[root]):
                root_surface[root] = raw_word
    
    # Sort by frequency, then return top N using surface forms
    sorted_roots = sorted(root_freq.items(), key=lambda x: x[1], reverse=True)
    return [root_surface.get(root, root) for root, _ in sorted_roots[:max_keywords]]

class TelegramNotificationGuard:
    @staticmethod
    def should_send(now_kst):
        # 1. 시간 기반(정기) 트리거 (우선 순위 상향)
        # 매 정시 0~10분 사이 또는 장마감 브리핑(15:30~15:55)
        is_top_of_hour = (0 <= now_kst.minute <= 10)
        is_market_close = (now_kst.hour == 15 and 30 <= now_kst.minute <= 55)
        
        if is_top_of_hour or is_market_close:
            return True, "Scheduled"

        # 2. 강제 실행 검사: FORCE_RUN이 명시적으로 true인 경우 (디버깅용)
        is_forced = os.environ.get('FORCE_RUN', 'false').strip().lower() == 'true'
        if is_forced:
            return True, "Forced Run"

        # 3. 그 외 이벤트(repository_dispatch, workflow_dispatch 등)는 시간 조건을 만족하지 않으면 전송하지 않음
        return False, None

def extract_meaningful_keywords(titles, stock_name, max_keywords=5):
    """
    Extracts meaningful keywords from post titles,
    filtering out noise words and the stock name itself.
    """
    # Break stock name into parts for filtering
    name_parts = {stock_name, stock_name[:2], stock_name[-2:]}
    
    word_freq = {}
    for title in titles:
        # Clean special chars but keep Korean/English/Numbers
        cleaned = re.sub(r'[^가-힣a-zA-Z0-9\s]', ' ', title)
        words = cleaned.split()
        
        for word in words:
            word = word.strip()
            # Basic filters: length, digit-only, stopwords
            if len(word) <= 1 or word.isdigit() or word in STOPWORDS or word.lower() in STOPWORDS:
                continue
            
            # Stock name part filter
            if any(part in word for part in name_parts if len(part) >= 2):
                continue
            
            # Common endings filter (verbs/adjectives/particles)
            if re.search(r'(다|요|까|죠|임|함|네|야|어|은|는|이|가|을|를|에|의|로|으로|고|면|서|도|만)$', word):
                if len(word) <= 3: continue 
            
            word_freq[word] = word_freq.get(word, 0) + 1
    
    # Sort and return top N
    sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
    return [w[0] for w in sorted_words[:max_keywords]]


def calculate_long_term_consecutive_days(current_codes):
    """
    Calculates consecutive days using a persistent JSON state.
    [V9.3] Fixed resetting issue by using db-data/data/consecutive_counts.json
    """
    import json
    state_path = 'db-data/data/consecutive_counts.json'
    now_kst = datetime.utcnow() + timedelta(hours=9)
    today_str = now_kst.strftime('%Y-%m-%d')
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    
    # 1. Load existing state
    state = {}
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
        except Exception as e:
            print(f"[Streak] Error loading state: {e}")
            state = {}
            
    new_state = {}
    consecutive_counts = {}
    
    # 2. Update streaks for current codes
    for code in current_codes:
        prev_data = state.get(code, {'count': 0, 'last_date': ''})
        prev_count = prev_data.get('count', 0)
        prev_date = prev_data.get('last_date', '')
        
        if prev_date == today_str:
            # Already updated today (multi-run safety)
            current_count = prev_count
        else:
            # New appearance or continued streak
            current_count = prev_count + 1
            
        new_state[code] = {
            'count': current_count,
            'last_date': today_str
        }
        consecutive_counts[code] = current_count
        
    # 3. Save new state (Only contains currently active streaks to keep JSON small)
    try:
        with open(state_path, 'w', encoding='utf-8') as f:
            json.dump(new_state, f, ensure_ascii=False, indent=2)
        print(f"[Streak] Persistent state saved to {state_path}")
    except Exception as e:
        print(f"[Streak] Error saving state: {e}")
        
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
# from src.features.gemini_agent import GeminiAgent  # [NEW] Import Gemini Agent <-- REMOVED (Inlined)
# from src import utils # Removed V7.0 (Legacy)

def load_env_manual(filepath=".env.local"):
    # Local .env support
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    key, val = line.strip().split('=', 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    # 환경 변수가 시스템에 명시적으로 잡혀있지 않을 때만 설정 (일원화)
                    if key not in os.environ:
                        os.environ[key] = val

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
    import time
    start_time_perf = time.perf_counter()
    print("[System] 스크래핑 프로세스 시작")

    # 0. Load Environment Variables & Validate [Grand Protocol v12]
    load_env_manual()
    
    try:
        from src.config_validator import validate_scraper, mask_sensitive
        is_val_ok, missing_vars = validate_scraper()
        if not is_val_ok:
            print("\n" + "!" * 60)
            print("[FATAL] 필수 환경 변수 검증 실패 - 시스템을 중단합니다.")
            for m in missing_vars: print(f"  ❌ {m}")
            print("!" * 60)
            sys.exit(1) # Silent Failure 방지
            
        print(f"[Scraper] 환경 변수 검증 통과. (Gemini Key: {mask_sensitive(os.environ.get('GEMINI_KEY') or os.environ.get('GOOGLE_API_KEY', ''))})")
    except ImportError:
        print("[Scraper] ⚠️  ConfigValidator 로드 실패. 기본 체크로 진행합니다.")
    
    # --- Branch Recovery (V9.5) ---
    try:
        import subprocess
        res = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True)
        current_branch = res.stdout.strip()
        if current_branch == 'db-data':
            print("[Warning] Script started on 'db-data' branch! Switching back to 'main'...")
            subprocess.run(['git', 'checkout', 'main'], check=False)
    except Exception as e:
        print(f"[System] Git branch check failed: {e}")

    # 1. Initialize Time & Threshold (CRITICAL FIX V6.7)
    now_kst = get_current_kst_time()
    current_hour = now_kst.hour
    
    # --- Force Run Support (V10.0) ---
    force_run_env = os.environ.get('FORCE_RUN', 'false').strip().lower() == 'true'
    
    if force_run_env:
        print("[System] FORCE_RUN=true detected. Threshold set to 1 and bypassing market check.")
        threshold = 1
    else:
        threshold = get_threshold_by_time(current_hour)
    
    now = now_kst # Sync variable name for later use
    
    print(f"[System] Time (KST): {now_kst.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # --- Market Holiday Check (V6.8) ---
    import holidays
    kr_holidays = holidays.KR()
    
    is_weekend = now_kst.weekday() >= 5 # 5=Sat, 6=Sun
    is_holiday = now_kst.strftime('%Y-%m-%d') in kr_holidays
    
    if (is_weekend or is_holiday) and not force_run_env:
        reason = "Weekend" if is_weekend else f"Holiday ({kr_holidays.get(now_kst.strftime('%Y-%m-%d'))})"
        print(f"[System] Market Closed Today ({reason}). Skipping execution.")
        sys.exit(0) # Exit cleanly, no Telegram sent.
    elif force_run_env and (is_weekend or is_holiday):
        print(f"[System] Market is closed, but BYPASSING due to FORCE_RUN=true.")
        
    print(f"[System] Threshold determined: {threshold} posts (based on hour {current_hour})")

    # --- [Grand Protocol] 환경 변수 사전 검증 ---
    try:
        from src.config_validator import validate_scraper
        _scraper_ok, _scraper_missing = validate_scraper()
        if not _scraper_ok:
            print("[System] ⚠️  일부 환경 변수 누락. 해당 기능은 비활성화됩니다.")
    except Exception as _cv_err:
        print(f"[System] ConfigValidator 로드 실패: {_cv_err}")

    # --- [Grand Protocol] NotificationService 초기화 (단일 진입점) ---
    try:
        from src.notification.notification_service import NotificationService
        notif_service = NotificationService()
    except Exception as e:
        print(f"[System] NotificationService 초기화 실패: {e}")
        notif_service = None

    # 하위 호환성: 기존 tg_manager 변수도 유지
    tg_manager = notif_service._tg if (notif_service and notif_service.is_available) else None
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
                candidates_posts = raw_latest[:10] 
                
                combined_body = ""
                print(f"   [dtl] {stock['name']}: {recent_count} (Fetching bodies...)")
                for post in candidates_posts:
                    if post.get('link'):
                        b = fetch_post_body(post['link'])
                        post['body'] = b
                        combined_body += f"\n{b}"
                    else:
                        post['body'] = ""
                
                stock['latest_posts'] = candidates_posts
                stock['all_posts_titles'] = stats.get('all_posts_titles', []) 
                stock['post_count'] = recent_count # Match engine.py key

                # [NEW] Real-time Sentiment Analysis via Gemini (V9.8)
                try:
                    from src.strategy.advisor import GeminiAgent
                    sentiment_agent = GeminiAgent()
                    # Calculate positive rate from combined bodies
                    if combined_body.strip():
                        prompt = f"다음 주식 게시글들을 분석하여 긍정적인 의견의 비율(0~100)을 숫자로만 답변하세요: {combined_body[:2000]}"
                        res_text = sentiment_agent.model.generate_content(prompt).text
                        pos_rate = float(re.search(r'\d+', res_text).group())
                        stock['positive_rate'] = pos_rate
                    else:
                        stock['positive_rate'] = 50.0
                except Exception as e:
                    # [FIX] 지시사항: AI 분석 실패 시 원인을 로깅합니다.
                    print(f"   [Error] Sentiment analysis failed for {stock['name']}: {str(e)}")
                    stock['positive_rate'] = 50.0
                
                # Keywords
                titles = [p['title'] for p in candidates_posts]
                meaningful_kws = extract_meaningful_keywords(titles, stock.get('name', ''))
                stock['top_keywords'] = ", ".join(meaningful_kws) if meaningful_kws else ""

                # Consecutive Flag
                stock['foreign_rate_diff'] = stock.get('foreign_change_rate', 0.0) # Match engine.py key
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
    print(f"\n[System] Starting detailed analysis with Parallel Processing (Workers: 10)...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
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
    # --- Consolidated Analysis & Notification (V12 - Silent Failure Overhaul) ---
    try:
        from src.notification.notification_service import NotificationService
        notif_service = NotificationService()
        
        from src.telegram_manager import TelegramManager
        try:
            tg_manager = TelegramManager()
        except Exception:
            print("[Scraper] ⚠️  TelegramManager 초기화 실패 (NotificationService가 있다면 폴백 가능)")
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

        # [TELEGRAM V12 — Grand Protocol] Unified Notification Guard
        should_send_telegram, trigger_reason = TelegramNotificationGuard.should_send(now_kst)

        if trigger_reason:
            print(f"[System] Notification Triggered by: {trigger_reason}")

        # ── 전략 리포트 생성 (지능형 AI 호출 제어: 수동 실행 또는 정시 윈도우 0-10분 시에만 제미나이 작동) ───────
        advisor_report_text = ""
        is_market_close = (now_kst.hour == 15 and 0 <= now_kst.minute <= 30)
        is_forced = os.environ.get('FORCE_RUN', 'false').strip().lower() == 'true'
        
        # [지시사항] 깃허브 스케줄러가 아닌 모든 실행(Push, Manual, Dispatch)은 사용자의 의도가 담긴 수동형 실행으로 간주
        is_manual_run = os.environ.get('GITHUB_EVENT_NAME') != 'schedule' or is_forced
        is_time_window = 0 <= now_kst.minute <= 10
        
        # [지시사항] 수동 실행이거나 정시 윈도우인 경우에만 AI 호출
        should_run_ai = is_manual_run or is_time_window
        allow_buy = is_market_close or is_forced

        if all_data and should_run_ai:
            try:
                advisor = StrategyAdvisor()
                print(f"[System] 🧠 Gemini V2 Advisor 가동 (Reason: {'Manual' if is_manual else 'TimeWindow'}) - allow_buy={allow_buy}")
                advisor_report_text, _ = advisor.generate_report(all_data, allow_buy=allow_buy)
            except Exception as e:
                import traceback
                print(f"[ERROR] Strategy Advisor Failed: {type(e).__name__}: {e}")
                traceback.print_exc()
                advisor_report_text = f"[전략 리포트 분석 실패: {type(e).__name__}]"
        elif all_data and not should_run_ai:
            print(f"[System] 💤 AI 호출 건너뜀 (현재 {now_kst.minute}분: 정시 윈도우 아님)")

        if all_data and should_send_telegram:
            print("[System] Generating Consolidated Telegram Report via NotificationService...")

            records = result_df_kr.to_dict('records') if not result_df_kr.empty else []
            kospi_items = [r for r in records if r.get('시장구분') == 'KOSPI']
            kosdaq_items = [r for r in records if r.get('시장구분') == 'KOSDAQ']

            # ── NotificationService 를 통한 전송 (Traceback 가시화 적용) ────────
            report_success = False
            if notif_service and notif_service.is_available:
                report_success = notif_service.send_hourly_report(
                    kospi_records=kospi_items,
                    kosdaq_records=kosdaq_items,
                    advisor_report_text=advisor_report_text,
                    dashboard_url=os.environ.get('DASHBOARD_URL', 'https://stockbot-phi.vercel.app'),
                )
            elif tg_manager:
                print("[System] Fallback: Using tg_manager directly.")
                try:
                    tg_manager.send_market_report('KOSPI', kospi_items)
                    tg_manager.send_market_report('KOSDAQ', kosdaq_items)
                    if advisor_report_text:
                        tg_manager.send_message(f"🧠 <b>[Strategic Guide]</b>\n{advisor_report_text[:3500]}")
                    report_success = True
                except Exception:
                    print("[Fallback] 전송 실패!")
                    traceback.print_exc()

            if not report_success:
                print("\n[Scraper] ❌ [CRITICAL] 알림 전송 실패가 감지되었습니다. 로그를 확인하세요.")
                # 알림이 치명적 기능이므로 실패 시 명시적으로 종료 코드 1 반환
                sys.exit(1)
            else:
                print("[Scraper] ✅ 텔레그램 리포트 전송 완료.")

        elif not all_data and should_send_telegram:
            if notif_service and notif_service.is_available:
                notif_service.send_no_data_alert(threshold)
            elif tg_manager:
                try:
                    tg_manager.send_no_data_alert(threshold)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    print(f"[System] No-data alert 전송 실패: {e}")
        elif not should_send_telegram:
            print(f"[System] Skipped notification (not top of hour): {now_kst.strftime('%H:%M')}")

        # --- 4. Gemini Portfolio Simulator (Regime-Aware & Static Model) ---
        print("\n[System] Entering Gemini Portfolio Simulator...")
        try:
            from src.strategy.hybrid_advisor_sandbox import HybridAnalyzerSandbox
            from src.trade.gemini_trade import GeminiTrader
            
            # 1. Market Regime Detection (KOSPI/KOSDAQ)
            def get_market_regime():
                try:
                    url = "https://finance.naver.com/sise/"
                    res = requests.get(url, timeout=5)
                    soup = BeautifulSoup(res.text, 'html.parser')
                    kos_now = soup.select_one("#KOSPI_now")
                    kospi = float(kos_now.text.replace(',', '')) if kos_now else 2500.0
                    
                    daq_now = soup.select_one("#KOSDAQ_now")
                    kosdaq = float(daq_now.text.replace(',', '')) if daq_now else 800.0
                    
                    kospi_change_tag = soup.select_one("#KOSPI_change")
                    kospi_change = kospi_change_tag.text.strip() if kospi_change_tag else "0"
                    is_bull = "+" in kospi_change
                    
                    regime = "BULL" if is_bull else "BEAR"
                    return regime, {"KOSPI": kospi, "KOSDAQ": kosdaq}
                except Exception as re_e:
                    print(f"  [Warning] Regime detection failed: {re_e}")
                    return "NEUTRAL", {"KOSPI": 2500, "KOSDAQ": 800}

            regime, indices = get_market_regime()
            print(f"  [System] Market Regime: {regime} ({indices})")

            # 2. Load Static Model (Dynamic Path for CI/CD)
            model_ver = "v2026-01-02--2026-02-28"
            base_dir = os.path.dirname(os.path.abspath(__file__))
            model_path = os.path.join(base_dir, "src", "strategy", "models", f"{model_ver}.joblib")
            archive_file = os.path.join(base_dir, "scraping data", "combined_scraping_data.csv")
            
            # Fallback for CI if archive file doesn't exist (can use latest stock data as proxy if needed, but for now just check existence)
            if not os.path.exists(archive_file):
                print(f"  [Warning] Archive file not found at {archive_file}. AI Simulator might have limited context.")
            
            sandbox = HybridAnalyzerSandbox(data_path=archive_file, model_path=model_path, version=model_ver)
            
            if sandbox.ml_model:
                trader = GeminiTrader()
                trader.state['algo_version'] = model_ver
                trader.state['market_regime'] = regime
                
                # Predict ML probabilities for current candidates
                current_data_map = {}
                all_ml_probs = []
                
                if 'all_data' in locals() and all_data:
                    print(f"  [System] Running ML predictions for {len(all_data)} trending stocks...")
                    all_ml_probs = sandbox.predict_all(all_data)
                    for pick in all_ml_probs:
                        current_data_map[pick['code']] = {
                            'price': pick.get('price', 0),
                            'ml_prob': pick.get('ml_prob', 50.0)
                        }
                else:
                    print("  [System] No trending stocks in this run. Checking existing portfolio.")

                # IMPORTANT: Fetch current prices for stocks already in portfolio
                for code in list(trader.state['holdings'].keys()):
                    if code not in current_data_map:
                        try:
                            h_name = trader.state['holdings'][code].get('name', '')
                            # print(f"  [System] Fetching price for portfolio stock: {h_name} ({code})")
                            res_h = requests.get(f"https://finance.naver.com/item/main.naver?code={code}", timeout=5)
                            soup_h = BeautifulSoup(res_h.text, 'html.parser')
                            price_tag = soup_h.select_one(".no_today .blind")
                            if price_tag:
                                h_price = int(price_tag.text.replace(',', ''))
                                current_data_map[code] = {
                                    'price': h_price,
                                    'ml_prob': 50.0 # Neutral prob if not in trending list
                                }
                        except Exception as e:
                            print(f"  [Warning] Failed to fetch price for {code}: {e}")

                # Execute Portfolio Logic
                trader.check_exits(current_data_map)
                
                top_ml_picks = sorted(all_ml_probs, key=lambda x: x['ml_prob'], reverse=True)[:5]
                trader.execute_buys(top_ml_picks)
                
                print("[System] Gemini Portfolio Simulator run complete.")
            else:
                print("  [ERROR] Static model loading failed. Rebalancing skipped.")
                
        except Exception as e:
            print(f"  [ERROR] Gemini Simulator Failed: {e}")
            import traceback
            traceback.print_exc()

    except Exception as e:
        print(f"\n[CRITICAL ERROR] Failed in consolidated section: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


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

        # Auto-push is now handled by scraper.yml workflow for better security and stability.
        pass

        end_time_perf = time.perf_counter()
        elapsed_time = end_time_perf - start_time_perf
        print(f"\n[System] 스크래핑 프로세스 완전 종료 (Execution Time: {elapsed_time:.2f} seconds)")










