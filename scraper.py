import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import sys



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
            
            return data[:30] # 상위 30개로 축소 (Top 30 Focus - User Request V7.5)
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

        return data[:20] # Top 20 as requested
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

        return data[:20] # Top 20 as requested
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
    
    for code, stock in unique_candidates.items():
        # ... logic ...
        # Need to iterate values
        pass 

    # Refactor loop to use dict values
    for stock in unique_candidates.values():
        market = stock['market']
        # Proceed with Detail Fetching & Threshold Check
        try:
             # 1. 상세 정보 (전일종가, 외국인)
            details = get_stock_details(stock['code'])
            stock.update(details)
            
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
                
                # Keywords (for Sentinel-V)
                titles = [p['title'] for p in candidates_posts]
                stock['top_keywords'] = ", ".join(titles[:3]) if titles else ""

                # Consecutive Flag
                if stock['code'] in yesterday_codes:
                    stock['is_consecutive'] = True
                else:
                    stock['is_consecutive'] = False

                all_data.append(stock)
                count_collected += 1
                # print(f" [KEEP] {stock['name']}: {recent_count} posts")
            else:
                pass

        except Exception as e:
            print(f"Error processing {stock['name']}: {e}")
            continue

    print(f"\n[System] Final Collected Items: {len(all_data)}")
    # --- Consolidated Analysis & Notification (V8.0) ---
    try:
        from src.telegram_manager import TelegramManager
        from src.features.sentinel_v import SentinelV
        
        try:
            tg_manager = TelegramManager()
        except:
            tg_manager = None
            
        import json
        os.makedirs('data', exist_ok=True)
        
        json_records = []
        result_df_kr = None
        
        if all_data:
            print(f"\nAnalyzing total {len(all_data)} items...")
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
            saved_files = analyzer.save_data(result_df_kr, filename_prefix=filename_prefix, extra_sheets=extra_sheets)
            
            # monthly report
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
                
                # 1. Market Summary
                summary_msg = f"📊 <b>[StockBot] Market Report ({datetime.now().strftime('%H:%M')})</b>\n\n"
                
                records = result_df_kr.to_dict('records')
                kospi_items = [r for r in records if r.get('시장구분') == 'KOSPI']
                kosdaq_items = [r for r in records if r.get('시장구분') == 'KOSDAQ']
                
                if kospi_items:
                    summary_msg += f"<b>[KOSPI]</b> {len(kospi_items)} items\n"
                    # Top 3 only
                    for item in kospi_items[:3]:
                        summary_msg += f"- {item['종목명']} ({item['등락률']}): {item['당일_게시글수']} posts\n"
                    if len(kospi_items) > 3: summary_msg += f"... and {len(kospi_items)-3} more\n"
                    summary_msg += "\n"
                    
                if kosdaq_items:
                    summary_msg += f"<b>[KOSDAQ]</b> {len(kosdaq_items)} items\n"
                    for item in kosdaq_items[:3]:
                        summary_msg += f"- {item['종목명']} ({item['등락률']}): {item['당일_게시글수']} posts\n"
                    if len(kosdaq_items) > 3: summary_msg += f"... and {len(kosdaq_items)-3} more\n"
                    summary_msg += "\n"

                # 2. Sentinel-V
                sentinel_msg = ""
                sentinel = SentinelV()
                buy_signals = []
                sell_signals = []
                
                for stock in all_data:
                    signal, reason = sentinel.analyze_stock(stock)
                    if "BUY" in signal:
                        buy_signals.append(f"🔴 <b>매수 신호</b>: {stock['name']} ({signal})\n   └ {reason}")
                    elif "SELL" in signal:
                        sell_signals.append(f"🔵 <b>매도 신호</b>: {stock['name']} ({signal})\n   └ {reason}")
                
                if buy_signals or sell_signals:
                    sentinel_msg = "⚡ <b>[Sentinel-V Signals]</b>\n" + "\n".join(buy_signals + sell_signals) + "\n\n"
                else:
                    sentinel_msg = "⚡ <b>[Sentinel-V]</b> 특이 매매 신호 없음\n\n"

                # 3. Expert Guide
                expert_msg = ""
                try:
                    gemini = GeminiAgent()
                    if gemini.model:
                        # Pass ALL data to Gemini
                        guide_text = gemini.generate_trading_guide(all_data)
                        expert_msg = f"🧠 <b>[Expert Guide]</b>\n{guide_text}\n\n"
                except Exception as user_e:
                    print(f"Gemini Error: {user_e}")

                # 4. Dashboard
                dash_msg = f"👉 <b>Dashboard</b>: {os.environ.get('DASHBOARD_URL', '')}"

                final_msg = summary_msg + sentinel_msg + expert_msg + dash_msg
                
                if len(final_msg) > 4000:
                    tg_manager.send_message(summary_msg + sentinel_msg)
                    tg_manager.send_message(expert_msg + dash_msg)
                else:
                    tg_manager.send_message(final_msg)
                    
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









