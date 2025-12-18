import pandas as pd
import os
from datetime import datetime


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
    
    # 1. 컬럼 매핑 (내부이름 -> 한글이름)
    col_map = {
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
        'is_last_captured': '연속_등록'
    }
    
    # 2. 존재하는 컬럼만 선택하여 순서 지정
    # 종목코드는 식별용으로 맨 앞에 두는 것이 관례이나, 사용자 요청 순서가 명확하므로 '종목명'을 맨 앞에 두고 커스텀 순서 배치
    desired_order = [
        'market', 'name', 'price', 'foreign_rate', 'prev_close', 'prev_foreign_rate', 
        'change_rate', 'recent_posts_count', 'posts_summary', 
        'sentiment', 'top_keywords', 'is_last_captured'
    ]
    
    final_cols = [c for c in desired_order if c in df_final.columns]
    
    # 사용자 요청에 없지만 중요한 'code'는 맨 앞에 숨겨두거나 제외? 일단 포함.
    if 'code' in df_final.columns:
        final_cols.insert(1, 'code') # market 다음, name 앞

    df_result = df_final[final_cols].rename(columns=col_map)


    print("\n[Analysis Result] Top Trending Stocks")
    print(df_result.head(10))

    return df_result, df_final[final_cols]




    return df_sorted


def save_data(df, filename_prefix="trending_stocks"):
    """
    DataFrame을 CSV 및 Excel 파일로 저장합니다.
    파일명에 타임스탬프를 포함합니다.
    저장된 파일명의 딕셔너리를 반환합니다.
    """
    if df.empty:
        print("No data to save.")
        return {}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{filename_prefix}_{timestamp}"
    csv_filename = f"{base_name}.csv"
    xlsx_filename = f"{base_name}.xlsx"
    
    saved_files = {}

    # 1. Save CSV
    try:
        df.to_csv(csv_filename, index=False, encoding='utf-8-sig')
        print(f"\nData saved to CSV: {os.path.abspath(csv_filename)}")
        saved_files['csv'] = csv_filename
    except Exception as e:
        print(f"Error saving to CSV: {e}")

    # 2. Save Excel
    try:
        df.to_excel(xlsx_filename, index=False, engine='openpyxl')
        print(f"Data saved to Excel: {os.path.abspath(xlsx_filename)}")
        saved_files['excel'] = xlsx_filename
    except Exception as e:
        print(f"Error saving to Excel: {e}")
        
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
        
        # 3. 게시글 요약 (조회수 상위 3개 제목 병합)
        # latest_posts 딕셔너리 리스트 활용, views를 숫자로 변환하여 정렬
        summary_text = ""
        if isinstance(latest_posts, list) and latest_posts:
            # views 문자열 처리 ('1,234' -> 1234)
            for p in latest_posts:
                if isinstance(p.get('views'), str):
                     try:
                        p['views_int'] = int(p['views'].replace(',', ''))
                     except:
                        p['views_int'] = 0
                else:
                    p['views_int'] = 0
            
            sorted_posts = sorted(latest_posts, key=lambda x: x['views_int'], reverse=True)
            top_posts = sorted_posts[:3]
            summary_text = " / ".join([p['title'] for p in top_posts])
            
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
        
        # 주요 키워드 Top 3
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
        # 현재 디렉토리의 csv 파일 목록 검색
        files = [f for f in os.listdir('.') if f.startswith('trending_stocks_') and f.endswith('.csv')]
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
             
        last_file = target_file
        # 주의: 이 함수는 save_to_csv 호출 '전'에 불려야 함.
        
        print(f"Comparing with history file: {last_file}")
        try:
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

