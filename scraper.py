import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import time


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
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
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
    - 당일 09:00 이후 게시글 정밀 카운팅
    - 전수 조사를 위해 페이지네이션 수행
    """
    
    # 기준 시간 설정 (당일 09:00)
    # 실제 운영 시에는 '현재 날짜' 기준 09:00로 설정
    now = datetime.now()
    target_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    # 만약 현재 시간이 09:00 이전이라면? -> 전일 09:00? 아니면 당일 0시?
    # 보통 장 시작 이후를 의미하므로, 9시 이전이면 "아직 장 시작 전"이라 게시글이 적을 수 있음.
    # 일단 '오늘 9시' 기준으로 잡되, 현재가 9시 이전이면 '어제 9시'부터?
    # 사용자 요구사항: "당일 09:00 이후" -> 명확함.
    
    if now < target_time:
        # 9시 이전이면 카운트 0일 수 있음. (혹은 어제 글을 보라는 건지? 일단 문자 그대로 당일 09시 기준)
        pass # 그냥 진행 (09:00 > 게시글 날짜 이므로 loop 바로 종료될 것임)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    collected_posts = []
    page = 1
    max_pages = 20 # 무한 루프 방지용 안전 장치
    stop_collecting = False
    
    headers['Referer'] = f"https://finance.naver.com/item/board.naver?code={code}"

    while page <= max_pages and not stop_collecting:
        url = f"https://finance.naver.com/item/board.naver?code={code}&page={page}"
        
        try:
            # 너무 빠른 요청 방지
            if page > 1:
                time.sleep(0.5)

            # 타임아웃 10초 설정
            response = requests.get(url, headers=headers, timeout=10)
            # BS4 자동 감지 맡김

            soup = BeautifulSoup(response.content, 'html.parser')
            
            table = soup.select_one('table.type2')
            if not table:
                break
                
            rows = table.select('tr')
            # 게시글 없으면 종료
            if not rows: 
                break
                
            found_post_in_page = False
            
            for row in rows:
                cols = row.select('td')
                if len(cols) < 5:
                    continue
                
                try:
                    # 날짜 확인
                    # 네이버 금융 날짜 포맷: "2024.05.21 14:30"
                    date_text = cols[0].get_text(strip=True)
                    
                    # 날짜 형식이 맞는지 확인 (가끔 공지사항 등이 섞일 수 있음)
                    try:
                        post_date = datetime.strptime(date_text, "%Y.%m.%d %H:%M")
                    except ValueError:
                        # 날짜 파싱 실패 시 무시 (헤더나 공지일 수 있음)
                        continue
                        
                    found_post_in_page = True

                    # 기준 시간 체크
                    if post_date < target_time:
                        stop_collecting = True
                        break # 더 이상 볼 필요 없음 (과거 글)
                    
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
                        'date': date_text, # 원본 텍스트 유지 (표시용)
                        'views': views
                    })
                    
                except Exception:
                    continue
            
            # 페이지에 유효한 게시글 태그가 하나도 없었다면? (구조 변경 등) -> 다음 페이지 가봐야 함?
            # 아니면 그냥 종료?
            # 일단 found_post_in_page가 False여도(공지사항만 있거나) 다음 페이지 시도할 수 있음.
            # 하지만 보통 1페이지에 없으면 데이터가 없는 것.
            
            page += 1
            
        except Exception as e:
            print(f"Error fetching page {page} for {code}: {e}")
            break
            
    return {
        'code': code,
        'recent_posts_count': len(collected_posts), # 정밀 카운팅 된 숫자
        'latest_posts': collected_posts[:5], # 분석용으로는 전체가 필요할 수 있으나, 리턴은 일부만 (Analyzer에는 전체 전달 필요하면 구조 수정)
        'all_posts_titles': [p['title'] for p in collected_posts] # 감성 분석용 전체 제목 리스트
    }




import analyzer
from src import research_scraper
from src import utils # For robust telegram sending if needed, or use telegram_plugin

def load_env_manual(filepath=".env.local"):
    # ... (existing code) ...
    pass

if __name__ == "__main__":
    # 0. Load Environment Variables
    load_env_manual()
    
    # ... check time ...
    
    # 1. Research Briefing (Enabled)
    print("\n[Research] Updating Market Briefing & PDF Analysis...")
    try:
        # Check if research_scraper has main() or fetch_research_data()
        # Based on previous view, it has main() which saves json.
        # We should call main() or the core function.
        # research_scraper.main() seems to do everything including saving JSON.
        research_scraper.main()
        print("[Research] Completed.")
        
        # Send Research Telegram
        try:
            import json
            with open('data/latest_research.json', 'r', encoding='utf-8') as f:
                r_data = json.load(f)
            
            invest_summary = r_data.get('invest', {}).get('summary', '요약 없음')
            items_count = r_data.get('invest', {}).get('today_count', 0)
            
            r_msg = f"📑 [리포트 브리핑] 총 {items_count}건\n\n"
            r_msg += f"💡 시장 요약: {invest_summary[:300]}...\n\n"
            r_msg += f"👉 자세히 보기: {os.environ.get('DASHBOARD_URL', '')}"
            
            import telegram_plugin
            telegram_plugin.send_telegram_message(r_msg)
            print("[Research] Telegram Sent.")
            
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
            # Performance safety / Limit (User Request V6.2: 30 stocks)
            if i >= 30: break 
            
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

    if all_data:
        print(f"\nAnalyzing total {len(all_data)} items...")
        result_df = analyzer.analyze_discussion_trend(all_data)
        
        # 통합 파일로 저장
        filename = f"trending_integrated"
        analyzer.save_to_csv(result_df, filename_prefix=filename)

        # Telegram Notification
        try:
            import telegram_plugin
            import os
            
            # Format message
            # Split Messages (User Request V6.6: Link FIRST, then Data)
            
            # 1. Dashboard Link (FIRST PRIORITY)
            dashboard_url = os.environ.get('DASHBOARD_URL', '')
            if dashboard_url:
                 telegram_plugin.send_telegram_message(f"📊 <b>Dashboard Check</b>\n{dashboard_url}")
                 time.sleep(1)

            # 2. KOSPI Message
            kospi_stocks = [x for x in all_data if x['market']=='KOSPI']
            if kospi_stocks:
                sorted_k = sorted(kospi_stocks, key=lambda x: x['recent_posts_count'], reverse=True)
                msg_k = f"📉 [KOSPI] ({len(kospi_stocks)} items)\n"
                for s in sorted_k[:10]: # Top 10 only per message
                     msg_k += f"🔥 <b>{s['name']}</b>: {s['recent_posts_count']}글 | {s.get('change_rate','-')}\n"
                
                # Check message length safety (optional, but good practice)
                telegram_plugin.send_telegram_message(msg_k)
                time.sleep(1)

            # 3. KOSDAQ Message
            kosdaq_stocks = [x for x in all_data if x['market']=='KOSDAQ']
            if kosdaq_stocks:
                sorted_q = sorted(kosdaq_stocks, key=lambda x: x['recent_posts_count'], reverse=True)
                msg_q = f"📉 [KOSDAQ] ({len(kosdaq_stocks)} items)\n"
                for s in sorted_q[:10]:
                     msg_q += f"🔥 <b>{s['name']}</b>: {s['recent_posts_count']}글 | {s.get('change_rate','-')}\n"
                telegram_plugin.send_telegram_message(msg_q)
            
        except ImportError:
            pass
        except Exception as e:
            print(f"Failed to send finish notification: {e}")

    else:
        print("No data collected meeting the threshold.")
        # User Request: Send notification even if empty, so we know it ran.
        try:
            import telegram_plugin
            import os
            
            dashboard_url = os.environ.get('DASHBOARD_URL', '')
            
            # 1. Dashboard Link (Checking Alive)
            if dashboard_url:
                 telegram_plugin.send_telegram_message(f"📊 <b>Dashboard Check (No Data)</b>\n{dashboard_url}")
                 time.sleep(1)
                 
            # 2. Status Message
            msg = f"📉 [Report] {datetime.now().strftime('%H:%M')}\n"
            msg += f"Threshold: {threshold} posts\n"
            msg += "Info: 조건에 맞는 급상승 종목이 없습니다. (No stocks found)"
            
            telegram_plugin.send_telegram_message(msg)
            
        except Exception as e:
            print(f"Failed to send empty notification: {e}")







