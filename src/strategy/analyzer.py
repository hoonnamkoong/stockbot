import pandas as pd
import os
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import os


def analyze_discussion_trend(data_list):
    """
    수집된 토론실 데이터를 기반으로 트렌드를 분석합니다.
    """
    if not data_list:
        print("No data to analyze.")
        return pd.DataFrame()
        
    df = pd.DataFrame(data_list)
    
    # 등락률 기준 정렬 (문자열 '%' 제거 및 float 변환 필요)
    try:
        df['change_rate_val'] = df['change_rate'].str.replace('%', '').astype(float)
        df_sorted = df.sort_values(by='change_rate_val', ascending=False)
    except Exception as e:
        print(f"Sort failed: {e}")
        df_sorted = df
        
    # 추가 분석: 감성 분석 및 키워드 요약
    df_analyzed = analyze_sentiment(df_sorted)
    
    # 추가 분석: 과거 이력 비교
    df_final = compare_with_history(df_analyzed)
    
    # [사용자 요청] 컬럼 순서 및 한글 이름 변경
    # 순서: 현재가, 현재 외국인 비중, 어제 종가, 어제 외국인 비중, 어제 대비 등락률, 당일 게시글 수, 당일 게시물 주요 내용 요약 (3문장 이내), 감정 분석, top keyword, 연속 등록
    
    # 1. 컬럼 매핑 (User Screenshot Matching)
    # 1. 컬럼 매핑 (User Screenshot Matching)
    col_map = {
        'market': '시장구분',
        'name': '종목명',
        'price': '현재가',
        'foreign_rate': '현재_외국인비중',
        'prev_close': '어제_종가',
        'prev_foreign_rate': '어제_외국인비중',
        'change_rate': '등락률',
        'foreign_change_rate': '외인변화', # [Added]
        'recent_posts_count': '당일_게시글수',
        'posts_summary': '게시물_요약',
        'sentiment': '감정분석',
        'top_keywords': 'Top_Keyword',
        'consecutive_days': '연속_등록', # [FIXED] Use calculated count
        'scraper_version': 'scraper_version' # [Added]
    }
    
    # 2. 존재하는 컬럼만 선택하여 순서 지정
    desired_order = [
        'name', 'price', 'change_rate', 'foreign_change_rate', 'recent_posts_count', 'foreign_rate', 'market',
        'prev_close', 'prev_foreign_rate', 'posts_summary', 
        'sentiment', 'top_keywords', 'consecutive_days', 'latest_posts', 'scraper_version'
    ]
    
    final_cols = [c for c in desired_order if c in df_final.columns]
    
    # code는 식별용으로 남겨둠
    if 'code' in df_final.columns:
        final_cols.append('code') 

    df_result = df_final[final_cols].rename(columns=col_map)


    print("\n[Analysis Result] Top Trending Stocks")
    print(df_result.head(10))

    return df_result, df_final[final_cols]




    return df_sorted


def save_data(df, filename_prefix="trending_stocks", extra_sheets=None):
    """
    DataFrame을 CSV 및 Excel 파일로 저장합니다.
    파일명에 타임스탬프를 포함합니다.
    extra_sheets: { 'SheetName': DataFrame } 형태의 추가 시트 데이터
    저장된 파일명의 딕셔너리를 반환합니다.
    """
    if df.empty:
        print("No data to save.")
        return {}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"data/{filename_prefix}_{timestamp}"
    csv_filename = f"{base_name}.csv"
    xlsx_filename = f"{base_name}.xlsx"
    
    saved_files = {}

    # 1. Save CSV (Main Data Only)
    try:
        df.to_csv(csv_filename, index=False, encoding='utf-8-sig')
        print(f"\nData saved to CSV: {os.path.abspath(csv_filename)}")
        saved_files['csv'] = csv_filename
    except Exception as e:
        print(f"Error saving to CSV: {e}")

    # 2. Save Excel (Multi-sheet support)
    try:
        with pd.ExcelWriter(xlsx_filename, engine='openpyxl') as writer:
            # Main Sheet
            df.to_excel(writer, sheet_name='Trending_Stocks', index=False)
            
            # Extra Sheets
            if extra_sheets:
                for sheet_name, sheet_df in extra_sheets.items():
                    if not sheet_df.empty:
                        sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)
                        
        print(f"Data saved to Excel: {os.path.abspath(xlsx_filename)}")
        saved_files['excel'] = xlsx_filename
    except Exception as e:
        print(f"Error saving to Excel: {e}")
        
    # 3. [V8.6.0] Save Fixed Filename for Vercel Dashboard (Overwrite Guarantee)
    try:
        # data 디렉토리가 없을 경우 생성 (보안 레이어)
        os.makedirs('data', exist_ok=True)
        
        fixed_csv = "data/trending_integrated.csv"
        fixed_xlsx = "data/trending_integrated.xlsx"
        fixed_json = "data/latest_stocks.json"
        
        # Overwrite CSV (Force Sync)
        df.to_csv(fixed_csv, index=False, encoding='utf-8-sig')
        
        # [V8.6.2 Hotfix] Save JSON for Vercel/GitHub Dashboard
        df_json = df.to_json(orient='records', force_ascii=False)
        with open(fixed_json, 'w', encoding='utf-8') as f:
            f.write(df_json)
        
        # [V8.6.2 Hotfix] Update status.json with current KST
        now_kst = (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
        status_json = "data/status.json"
        with open(status_json, 'w', encoding='utf-8') as f:
            json.dump({"last_updated": now_kst, "status": "ok", "message": "Synced V8.6.2"}, f, ensure_ascii=False, indent=4)

        # Overwrite Excel (Force Sync)
        with pd.ExcelWriter(fixed_xlsx, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Trending_Stocks', index=False)
            if extra_sheets:
                for sheet_name, sheet_df in extra_sheets.items():
                    if not sheet_df.empty:
                        sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)
                        
        print(f"[Vercel] ✅ Fixed data synchronized: {fixed_csv}, {fixed_xlsx}")
    except Exception as e:
        print(f"[Vercel] 🚨 Error during fixed data synchronization: {e}")
        # 에러 발생 시 로그를 남기되 프로세스 전체를 중단시키지는 않음 (Recovery 우선성)
        
    return saved_files


def analyze_sentiment(df):
    """
    게시글 제목을 기반으로 긍정/부정 비율과 주요 키워드를 분석합니다.
    """
    if 'all_posts_titles' not in df.columns:
        return df

    positive_keywords = ['상승', '급등', '호재', '대박', '매수', '가즈아', '축하', '수익', '기대', '찬티']
    negative_keywords = ['하락', '폭락', '악재', '손절', '매도', '망', '개미털기', '설거지', '폭망', '안티']
    
    sentiment_summaries = []
    keyword_summaries = []
    posts_summaries = [] 

    for idx, row in df.iterrows():
        titles = row.get('all_posts_titles', [])
        latest_posts = row.get('latest_posts', [])
        
        # 3. 게시글 요약 (Deep Dive Weighted Scoring V7.5)
        summary_text = ""
        if isinstance(latest_posts, list) and latest_posts:
            # Score Calculation
            for p in latest_posts:
                # 1. Base Score (Views + Likes*30)
                try:
                    views = int(p.get('views', '0').replace(',', ''))
                except:
                    views = 0
                try:
                    likes = int(p.get('likes', '0'))
                except:
                    likes = 0
                
                score = views + (likes * 30)

                # 2. Body Analysis (Length Penalty & Prediction Bonus)
                body = p.get('body', '')
                if body:
                    # Penalty: Short Content (<= 2 lines or < 50 chars)
                    if len(body) < 50 or len(body.split('\n')) <= 2:
                        score *= 0.2
                    
                    # Bonus: Prediction Keywords
                    prediction_keywords = ['목표', '예상', '전망', '분석', '이유']
                    if any(kw in body for kw in prediction_keywords):
                        score += 2000
                else: 
                     # No body (maybe scrape failed or not top 10) -> Default penalty or neutral?
                     # If these are top 10 recommended, they should have body. 
                     # If not in top 10, they keep base score.
                     pass

                p['score'] = score
            
            # Sort by Score Descending
            sorted_posts = sorted(latest_posts, key=lambda x: x.get('score', 0), reverse=True)
            top_posts = sorted_posts[:4] # Top 4 Weighted Summaries
            summary_text = " / ".join([p.get('title', '') for p in top_posts])
            
        posts_summaries.append(summary_text)

        if not isinstance(titles, list) or not titles:
            sentiment_summaries.append("Neutral")
            keyword_summaries.append("")
            continue
            
        pos_count = 0
        neg_count = 0
        word_counts = {}
        
        for title in titles:
            # 1. 감성 점수 계산
            for kw in positive_keywords:
                if kw in title:
                    pos_count += 1
            for kw in negative_keywords:
                if kw in title:
                    neg_count += 1
            
            # 2. 단어 빈도 계산 (간단하게 공백 기준 분리 - 조사 처리는 생략)
            words = title.split()
            for word in words:
                if len(word) > 1: # 1글자 제외
                    word_counts[word] = word_counts.get(word, 0) + 1
        
        # 감성 판정
        total = pos_count + neg_count
        if total == 0:
            sentiment = "Neutral"
        elif pos_count > neg_count:
            sentiment = f"Positive ({int(pos_count/total*100)}%)"
        elif neg_count > pos_count:
            sentiment = f"Negative ({int(neg_count/total*100)}%)"
        else:
            sentiment = "Mixed"
            
        sentiment_summaries.append(sentiment)
        
        # [Revised Logic] Prefer existing 'Top_Keyword' from scraper if available
        # Scraper saves as 'top_keywords' (v8.2)
        existing_kw = row.get('top_keywords') or row.get('Top_Keyword') or row.get('Top_Keywords', '')
        if existing_kw and isinstance(existing_kw, str) and len(existing_kw.strip()) > 1:
            keyword_summaries.append(existing_kw)
            # sentiment_summaries already appended above
            continue

        # 주요 키워드 Top 3 (Fallback)
        sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
        top_keywords = ", ".join([w[0] for w in sorted_words[:3]])
        keyword_summaries.append(top_keywords)
    
    df['sentiment'] = sentiment_summaries
    df['top_keywords'] = keyword_summaries
    df['posts_summary'] = posts_summaries
    
    return df


def compare_with_history(current_df):
    """
    가장 최근에 저장된 CSV 파일과 비교하여 '연속 포착(is_consecutive)' 여부를 확인합니다.
    """
    try:
        # Look in the 'data' directory (restored from db-data branch)
        data_dir = 'data'
        if not os.path.exists(data_dir):
            current_df['is_last_captured'] = False
            return current_df
            
        # Search for files with the new prefix: trending_integrated_
        files = [f for f in os.listdir(data_dir) if f.startswith('trending_integrated_') and (f.endswith('.xlsx') or f.endswith('.csv'))]
        if not files:
            current_df['is_last_captured'] = False
            return current_df
            
        # 가장 최신 파일 찾기 (User Request: "어제 마지막 데이터"와 비교)
        # 파일명 형식: trending_stocks_YYYYMMDD_HHMMSS.csv
        # 날짜 파싱 -> 오늘 날짜와 비교 -> 어제(또는 그 이전) 중 가장 최신 파일 선택
        
        files.sort(reverse=True) # 최신순 정렬
        
        today_str = datetime.now().strftime("%Y%m%d")
        target_file = None
        
        for f in files:
            # 파일명에서 날짜 추출 (trending_stocks_20240501_120000.csv)
            try:
                parts = f.split('_') # ['trending', 'stocks', '20240501', '120000.csv']
                if len(parts) >= 3:
                    file_date = parts[2]
                    # 오늘 날짜보다 작은 것 중 가장 먼저 나오는 것 (정렬되어 있으므로)
                    if file_date < today_str:
                        target_file = f
                        break
            except:
                continue
        
        # 만약 어제 데이터가 없으면? (오늘 첫 실행인데 어제 데이터 없으면 그냥 가장 최신 파일이라도 비교? 아니면 False?)
        # 사용자 의도: "새로운 데이터와 비교" -> 보통 연속성은 "바로 직전"보다는 "이전 사이클"의 의미가 강함.
        # 일단 어제 데이터 없으면, 전체 중 두번째 파일(오늘 이전 실행)이라도 가져옴.
        if not target_file and len(files) > 1:
             # 오늘 실행된 것 중 이전에 실행된 것
             # 현재 생성될 파일은 아직 리스트에 없으므로, files[0]이 바로 직전 파일임.
             target_file = files[0]

        if not target_file:
             current_df['is_last_captured'] = False
             return current_df
             
        last_file = os.path.join(data_dir, target_file)
        # 주의: 이 함수는 save_to_csv 호출 '전'에 불려야 함.
        
        print(f"Comparing with history file: {last_file}")
        try:
             if last_file.endswith('.xlsx'):
                 history_df = pd.read_excel(last_file)
             else:
                 history_df = pd.read_csv(last_file)
        except:
             # 빈 파일 등 에러 처리
             history_df = pd.DataFrame(columns=['code'])
        
        # 과거에 존재했던 종목 코드 집합
        prev_codes = set(history_df['code'].astype(str))
        
        # 현재 코드와 비교
        current_df['is_last_captured'] = current_df['code'].astype(str).isin(prev_codes)
        
    except Exception as e:
        print(f"Error checking history: {e}")
        current_df['is_last_captured'] = False
        
    return current_df

def filter_promising_stocks(df, criteria):
    """
    기준에 맞는 유망 종목을 필터링합니다.
    """
    return df


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
        print(f"[Analyzer] Fetching {market_type} trending stocks...")
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.content.decode('euc-kr', 'replace'), 'html.parser')
        table = soup.select_one('table.type_2')
        
        data = []
        if table:
            rows = table.select('tr')
            for row in rows:
                cols = row.select('td')
                if len(cols) < 10: continue
                
                name_tag = cols[1].select_one('a')
                if not name_tag: continue
                name = name_tag.get_text(strip=True)
                
                if any(kw in name.upper() for kw in exclude_keywords): continue

                code = name_tag['href'].split('code=')[-1]
                price_str = cols[2].get_text(strip=True).replace(',', '')
                current_price = int(price_str) if price_str.isdigit() else 0
                change_rate = cols[4].get_text(strip=True).strip()
                
                prev_close = 0
                try:
                    rate_float = float(change_rate.replace('%', ''))
                    prev_close = int(current_price / (1 + rate_float/100))
                except: pass

                data.append({
                    'market': market_type,
                    'code': code,
                    'name': name,
                    'price': current_price,
                    'prev_close': prev_close,
                    'change_rate': change_rate,
                    'source': 'volume'
                })
        return data[:35]
    except Exception as e:
        print(f"[Error] get_top_trending_stocks failed: {e}")
        raise e # 에러 은폐 금지 (글로벌 룰)

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
        print(f"[Analyzer] Fetching {market_type} Rising stocks...")
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content.decode('euc-kr', 'replace'), 'html.parser')
        
        table = soup.select_one('table.type_2')
        data = []
        if table:
            rows = table.select('tr')
            for row in rows:
                cols = row.select('td')
                if len(cols) < 10: continue

                name_tag = cols[1].select_one('a')
                if not name_tag: continue
                name = name_tag.get_text(strip=True)
                
                if any(kw in name.upper() for kw in exclude_keywords): continue

                code = name_tag['href'].split('code=')[-1]
                price_str = cols[2].get_text(strip=True).replace(',', '')
                current_price = int(price_str) if price_str.isdigit() else 0
                change_rate = cols[4].get_text(strip=True).strip()
                
                data.append({
                    'market': market_type,
                    'code': code,
                    'name': name,
                    'price': current_price,
                    'change_rate': change_rate,
                    'source': 'rising'
                })
        return data[:35]
    except Exception as e:
        print(f"[Error] get_top_rising_stocks failed: {e}")
        raise e # 에러 은폐 금지 (글로벌 룰)
