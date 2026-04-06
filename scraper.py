import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import sys
import json
import concurrent.futures
import re

# [V8.4.1 Gold Master] 아키텍처 안정화 버전 (Date Parsing Fix)
SCRAPER_VERSION = "8.4.1 Gold Master"

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src', 'strategy')))
from src.strategy import analyzer
from src.strategy.advisor import StrategyAdvisor

def get_current_kst_time():
    return datetime.utcnow() + timedelta(hours=9)

def get_threshold_by_time(hour):
    if 9 <= hour < 12: return 40
    elif 12 <= hour < 14: return 60
    elif 14 <= hour < 24: return 100
    return 10

def load_env_manual():
    """
    [V8.4.2] .env 및 .env.local 호환 로드 및 API Key 상호 보완
    """
    for filepath in [".env", ".env.local"]:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip() and not line.startswith('#'):
                        try:
                            key, val = line.strip().split('=', 1)
                            os.environ[key.strip()] = val.strip().strip('"').strip("'")
                        except: continue

    # API Key 상호 호환 처리
    gemini_key = os.environ.get('GEMINI_KEY')
    google_key = os.environ.get('GOOGLE_API_KEY')
    if gemini_key and not google_key: os.environ['GOOGLE_API_KEY'] = gemini_key
    elif google_key and not gemini_key: os.environ['GEMINI_KEY'] = google_key

def fetch_post_body(link_suffix):
    try:
        url = f"https://finance.naver.com{link_suffix}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        time.sleep(0.3)
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.content, 'html.parser')
        body_tag = soup.select_one('#body') or soup.select_one('.view_se') or soup.select_one('.scr01')
        return body_tag.get_text(strip=True) if body_tag else ""
    except: return ""

def get_discussion_stats(code, threshold_time):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    collected_posts = []
    page = 1
    
    while page <= 15:
        url = f"https://finance.naver.com/item/board.naver?code={code}&page={page}"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(res.content, 'html.parser')
            rows = soup.select('table.type2 tr')
            
            for row in rows:
                cols = row.select('td')
                if len(cols) < 5: continue
                date_text = cols[0].get_text(strip=True)
                
                # [V8.4.2 핵심 수정] 당일 게시글(HH:MM)과 과거글(YYYY.MM.DD) 모두 대응
                try:
                    if ":" in date_text and "." not in date_text: # 당일글 (예: 21:15)
                        today_str = get_current_kst_time().strftime('%Y.%m.%d')
                        post_date = datetime.strptime(f"{today_str} {date_text}", "%Y.%m.%d %H:%M")
                    else: # 과거글 (예: 2026.04.05 15:30)
                        post_date = datetime.strptime(date_text, "%Y.%m.%d %H:%M")
                except: continue
                
                if post_date < threshold_time: 
                    return {'recent_posts_count': len(collected_posts), 'latest_posts': collected_posts}
                
                title_tag = row.select_one('a.title')
                if title_tag:
                    collected_posts.append({
                        'title': title_tag.get_text(strip=True),
                        'likes': cols[4].get_text(strip=True) if len(cols) > 4 else '0',
                        'link': title_tag['href']
                    })
            page += 1
        except: break
    return {'recent_posts_count': len(collected_posts), 'latest_posts': collected_posts}

def get_stock_details(code):
    details = {}
    url_frgn = f"https://finance.naver.com/item/frgn.naver?code={code}"
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url_frgn, headers=headers, timeout=10)
        soup = BeautifulSoup(res.content, 'html.parser')
        rows = soup.select('table.type_2 tr')
        data_rows = [r for r in rows if len(r.select('td')) > 5]
        if len(data_rows) >= 2:
            cols_today = data_rows[0].select('td')
            cols_yest = data_rows[1].select('td')
            details['foreign_rate'] = cols_today[-1].get_text(strip=True)
            details['prev_foreign_rate'] = cols_yest[-1].get_text(strip=True)
            prev_close = cols_yest[1].get_text(strip=True).replace(',', '')
            if prev_close.isdigit(): details['prev_close'] = int(prev_close)
    except: pass
    return details

def process_single_stock(stock, yesterday_codes, threshold, threshold_time):
    try:
        details = get_stock_details(stock['code'])
        stock.update(details)
        
        stats = get_discussion_stats(stock['code'], threshold_time)
        count = stats.get('recent_posts_count', 0)
        
        if count >= threshold:
            stock['recent_posts_count'] = count
            raw_posts = stats.get('latest_posts', [])
            raw_posts.sort(key=lambda x: int(x['likes']) if str(x['likes']).isdigit() else 0, reverse=True)
            best_posts = raw_posts[:5]
            for p in best_posts:
                p['body'] = fetch_post_body(p['link'])
            
            stock['latest_posts'] = best_posts
            stock['post_count'] = count
            stock['is_consecutive'] = stock['code'] in yesterday_codes
            return stock
        return None
    except Exception as e:
        print(f"[Error] {stock.get('name', 'Unknown')} 처리 중 오류: {e}")
        return None

if __name__ == "__main__":
    start_time = time.perf_counter()
    load_env_manual()
    now_kst = get_current_kst_time()
    
    force_run = os.environ.get('FORCE_RUN', 'false').lower() == 'true'
    threshold = 1 if force_run else get_threshold_by_time(now_kst.hour)
    threshold_time = now_kst.replace(hour=8, minute=0, second=0, microsecond=0)
    
    print(f"[System] V8.4.1 Gold Master 가동 (임계값: {threshold})")

    candidates = []
    for m in ['KOSPI', 'KOSDAQ']:
        candidates.extend(analyzer.get_top_trending_stocks(m))
        candidates.extend(analyzer.get_top_rising_stocks(m))
    
    unique_candidates = list({s['code']: s for s in candidates}.values())
    print(f"[System] 유니크 후보 {len(unique_candidates)}개 수집 완료")

    yesterday_codes = set() 
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_single_stock, s, yesterday_codes, threshold, threshold_time) for s in unique_candidates]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res: results.append(res)

    print(f"[System] 1단계 Buzz Filter 통과: {len(results)}개")

    advisor_report = ""
    elite_candidates = sorted(results, key=lambda x: x.get('recent_posts_count', 0), reverse=True)[:15]
    
    if elite_candidates:
        print(f"[System] Gemini Strategic Guide 생성 중...")
        advisor = StrategyAdvisor()
        advisor_report, _ = advisor.generate_report(elite_candidates, allow_buy=force_run or (now_kst.hour == 15))
    else:
        advisor_report = "⚠️ 금일 분석 기준(Buzz Threshold)을 충족하는 종목이 없습니다."

    if results:
        result_df_kr, _ = analyzer.analyze_discussion_trend(results)
        analyzer.save_data(result_df_kr, filename_prefix="trending_integrated")
        
        from src.notification.notification_service import NotificationService
        ns = NotificationService()
        if ns.is_available:
            summary_msg = f"🚀 **V8.4.1 Gold Master 전략 리포트**\n\n"
            summary_msg += f"일시: {now_kst.strftime('%Y-%m-%d %H:%M')}\n"
            summary_msg += f"분석 대상: {len(results)}개 종목\n\n"
            summary_msg += f"--- **Strategic Insights** ---\n\n"
            summary_msg += advisor_report[:3500] 
            
            ns._tg.send_message(summary_msg)
            print("[System] 텔레그램 리포트 전송 완료")

    print("[System] Simulator 가동 중...")
    from src.strategy.engine import StrategyEngine
    engine = StrategyEngine()
    engine.execute_simulation(results, allow_buy=force_run or (now_kst.hour == 15))

    elapsed = time.perf_counter() - start_time
    print(f"[System] 프로세스 종료 ({elapsed:.2f}s)")
