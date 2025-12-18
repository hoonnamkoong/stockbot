import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import sys

# sys.stdout.reconfigure 제거 (Next.js 환경변수 제어)

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
    }
    
    exclude_keywords = ['KODEX', 'TIGER', 'ETN', 'KBSTAR', 'ACE', 'KOSEF', 'SOL', 'HANARO', 'ARIRANG']
    
    try:
        if market_type == 'KOSPI':
             print(f"[DEBUG] Fetching KOSPI trending stocks...", flush=True)
        else:
             print(f"[DEBUG] Fetching KOSDAQ trending stocks...", flush=True)

        response = requests.get(url, headers=headers, timeout=10)
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
            
            return data[:100] # 상위 100개로 확대
        else:
            print(f"Stock table NOT found for {market_type}")
            return []

    except Exception as e:
        print(f"Error fetching trending stocks for {market_type}: {e}")
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
        response = requests.get(url_frgn, headers=headers)
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
    
    # 기준 시간 설정 (사용자 요청: 당일 00:01 이후)
    now = datetime.now()
    target_time = now.replace(hour=0, minute=1, second=0, microsecond=0)
    
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
                        'views': views
                    })
                    
                except Exception:
                    continue
            
            page += 1
            
        except Exception as e:
            print(f"Error fetching page {page} for {code}: {e}")
            break
            
    return {
        'code': code,
        'recent_posts_count': len(collected_posts),
        'latest_posts': collected_posts[:5], 
        'all_posts_titles': [p['title'] for p in collected_posts] 
    }




import analyzer
from src import research_scraper
        # from src import utils # Removed V7.0 (Legacy)

def load_env_manual(filepath=".env.local"):
    # ... (existing code) ...
    pass

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
    print("\n[Research] Updating Market Briefing & PDF Analysis...")
    try:
        from src import research_scraper # Ensure import
        research_scraper.main()
        print("[Research] Completed.")
        
        # Send Research Telegram
        try:
            import json
            # Correct path matches research_scraper.py output (data/latest_research.json)
            with open('data/latest_research.json', 'r', encoding='utf-8') as f:
                r_data = json.load(f)
            
            invest_summary = r_data.get('invest', {}).get('summary', '요약 없음')
            items_count = r_data.get('invest', {}).get('today_count', 0)
            
            r_msg = f"📑 <b>[리포트 브리핑] 총 {items_count}건</b>\n\n"
            r_msg += f"💡 시장 요약: {invest_summary[:300]}...\n\n"
            r_msg += f"👉 자세히 보기: {os.environ.get('DASHBOARD_URL', '')}"
            
            # tg_manager.send_message(r_msg) # User requested to disable Research Briefing (V7.1)
            print("[Research] Telegram Sent (Disabled by User Request).")
            
        except Exception as tg_e:
            print(f"[Research] Telegram Error: {tg_e}")
            
    except Exception as e:
        print(f"[Research] Error: {e}")

    markets = ['KOSPI', 'KOSDAQ']
    # ... (rest of code) ...
    
    all_data = [] # 통합 데이터 저장용

    for market in markets:
        print(f"\n[{market}] Starting collection...")
        # Get MORE stocks to ensure we find enough active ones (Top 100 instead of 20)
        trending_stocks = get_top_trending_stocks(market)
        # Limit to top 100 for performance (get_top_trending_stocks needs update to return more)
        # Assuming get_top_trending_stocks returns whatever it finds on page (usually 100 if not sliced)
        
        # In this edited version, we'll slice larger
        source_count = len(trending_stocks)
        print(f"Found {source_count} stocks in {market} Top list.")
        
        count_collected = 0
        
        for i, stock in enumerate(trending_stocks):
            # Performance safety / Limit (User Request V7.0: 20 stocks)
            if i >= 20: break 
            
            # 1. 상세 정보 (전일종가, 외국인)
            details = get_stock_details(stock['code'])
            stock.update(details)
            
            # 2. 토론방 정보 (시간 기준 카운팅)
            stats = get_discussion_stats(stock['code'])
            recent_count = stats.get('recent_posts_count', 0)
            
            # FILTER HERE
            if recent_count >= threshold:
                stock['recent_posts_count'] = recent_count
                stock['latest_posts'] = stats.get('latest_posts', [])
                stock['all_posts_titles'] = stats.get('all_posts_titles', []) 
                
                all_data.append(stock)
                count_collected += 1
                print(f" [KEEP] {stock['name']}: {recent_count} posts (Threshold {threshold})")
            else:
                # print(f" [SKIP] {stock['name']}: {recent_count} posts")
                pass

        print(f"Collected {count_collected} items from {market} meeting criteria.")

    # --- 5. Telegram Notification (Refactored V7.0 - Zero Base) ---
    try:
        from src.telegram_manager import TelegramManager
        try:
            tg_manager = TelegramManager()
            # DEBUG: Check credentials
            print(f"[DEBUG] Telegram Token Loaded: {bool(tg_manager.token)}")
            print(f"[DEBUG] Telegram Chat ID Loaded: {bool(tg_manager.chat_id)}")
        except Exception as e:
            print(f"[WARNING] Failed to initialize TelegramManager: {e}")
            tg_manager = None

        # Prepare Data for Saving (Always, even if empty)
        import json
        os.makedirs('data', exist_ok=True)
        
        if all_data:
            print(f"\nAnalyzing total {len(all_data)} items...")
            result_df_kr, result_df_en = analyzer.analyze_discussion_trend(all_data)
            json_records = result_df_en.to_dict('records')
            
            # Save CSV (History)
            filename = f"trending_integrated"
            analyzer.save_to_csv(result_df_kr, filename_prefix=filename)
        else:
            print(f"\n[System] No data collected (all below threshold {threshold}). Saving empty records.")
            json_records = []
            result_df_kr = None

        # Save JSON for Frontend (latest_stocks.json) - ALWAYS
        with open('data/latest_stocks.json', 'w', encoding='utf-8') as f:
            json.dump(json_records, f, ensure_ascii=False, indent=2)
        print(f"Data saved to data/latest_stocks.json (Count: {len(json_records)})")

        # [User Request V7.3] Save Time-Specific Snapshot - ALWAYS
        snapshot_name = None
        if 9 <= current_hour <= 10: snapshot_name = "stocks_1000.json"
        elif 12 <= current_hour <= 13: snapshot_name = "stocks_1300.json"
        elif 14 <= current_hour <= 23: snapshot_name = "stocks_1500.json" # Covers 14:00 ~ Midnight (Closing Data)
        
        if snapshot_name:
            with open(f'data/{snapshot_name}', 'w', encoding='utf-8') as f:
                json.dump(json_records, f, ensure_ascii=False, indent=2)
            print(f"Snapshot saved: data/{snapshot_name} (Count: {len(json_records)})")

        # Telegram Notifications
        if all_data:
            if tg_manager:
                try:
                    # Filter Lists
                    records = result_df_kr.to_dict('records')
                    kospi_items = [r for r in records if r.get('시장구분') == 'KOSPI']
                    kosdaq_items = [r for r in records if r.get('시장구분') == 'KOSDAQ']
                    
                    if kospi_items:
                        tg_manager.send_market_report('KOSPI', kospi_items)
                        time.sleep(1)
                        
                    if kosdaq_items:
                        tg_manager.send_market_report('KOSDAQ', kosdaq_items)
                        time.sleep(1)

                    # 2. Dashboard Link
                    print(f"[System] Sending Dashboard Link last... (v7.0)")
                    tg_manager.send_dashboard_link()
                except Exception as send_err:
                    print(f"[ERROR] details sending Telegram: {send_err}")
            else:
                 print("[System] TelegramManager not available. Skipping notifications.")
        else:
            print("No data collected meeting the threshold.")
            if tg_manager:
                print(f"[System] Sending No Data Alert (Threshold: {threshold})")
                try:
                    tg_manager.send_no_data_alert(threshold)
                except Exception as e:
                    print(f"[ERROR] Failed to send No Data Alert: {e}")

    except Exception as e:
        print(f"Failed in notification/saving section: {e}")

    finally:
        # Save Status JSON for Frontend (ALWAYS RUN)
        try:
            import json
            status_data = {
                "last_updated": now_kst.strftime('%Y-%m-%d %H:%M:%S'),
                "message": "Data updated successfully" if all_data else "No data collected",
                "count": len(all_data) if 'all_data' in locals() else 0
            }
            with open('data/status.json', 'w', encoding='utf-8') as f:
                json.dump(status_data, f, ensure_ascii=False, indent=2)
            print(f"[System] status.json updated at {status_data['last_updated']}")
        except Exception as status_e:
            print(f"[ERROR] Failed to save status.json: {status_e}")









