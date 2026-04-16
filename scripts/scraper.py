import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import sys
import json
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, as_completed
import re

# [V8.9.9.42] 월별 통합 리서치 및 정시 알림 보장 버전
# [Stage 1] 수집 및 문턱 필터링 + 시작 시각 고정(정시 알림 보장)
# [Stage 3] 월별 통합 엑셀 리포트(ROI 제외) 누적 생성
# [Stage 4] 텔레그램 전송 및 시뮬레이터 3종 주가 동기화
SCRAPER_VERSION = "8.9.9.42 Monthly Aggregated (ROI Excluded)"

# 경로 설정
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from src.strategy import analyzer
get_top_trending_stocks = analyzer.get_top_trending_stocks
from src.strategy.advisor import GeminiAgent
from src.strategy.engine import StrategyEngine
from src.strategy.simulators.sim1_original import OriginalSimulator
from src.strategy.simulators.sim2_conservative import ConservativeSimulator
from src.strategy.simulators.sim3_aggressive import AggressiveSimulator
from src.telegram_manager import TelegramManager

def get_current_kst_time():
    return datetime.utcnow() + timedelta(hours=9)

def get_threshold_by_time(hour):
    if 0 <= hour < 9: return 20
    elif 9 <= hour < 11: return 40
    elif 11 <= hour < 14: return 80
    elif 14 <= hour < 16: return 120
    return 130

def is_trading_day(dt):
    if dt.weekday() >= 5: return False
    holidays_2026 = ["01-01", "02-16", "02-17", "02-18", "03-01", "03-02", "05-05", "05-22", "06-06", "08-15", "09-24", "09-25", "09-26", "10-03", "10-09", "12-25", "12-31"]
    if dt.strftime('%m-%d') in holidays_2026: return False
    return True

def load_env_manual():
    """시스템 환경변수 및 로컬 .env 파일을 로딩합니다. (.env.production 우선)"""
    for filepath in [".env.production", ".env.final", ".env", ".env.local"]:
        if os.path.exists(filepath):
            try:
                from dotenv import load_dotenv
                load_dotenv(filepath)
                print(f"[Env] Loaded from {filepath}")
                # 주요 키가 로드되면 중단 (우선순위 보장)
                if os.environ.get('GEMINI_KEY') or os.environ.get('GOOGLE_API_KEY'):
                    break
            except:
                continue

def load_sync_state():
    state_path = 'data/sync_state.json'
    today_str = get_current_kst_time().strftime('%Y%m%d')
    yesterday_data = {}
    
    # 1. 타임스탬프로 캐시를 우회하여 db-data 브랜치에서 필요한 모든 상태 파일 로드
    import time
    import urllib.request
    
    # [V8.9.9.16 Persistence] 동기화 대상 파일 리스트 확장 (CSV 및 모든 월별 엑셀 포함)
    current_kst = get_current_kst_time()
    files_to_sync = [
        'sync_state.json',
        'sim_original_state.json',
        'sim_conservative_state.json',
        'sim_aggressive_state.json',
        'trade_history_sim_original.csv',
        'trade_history_sim_conservative.csv',
        'trade_history_sim_aggressive.csv',
        'trade_history_sim_conviction.csv',
        'reservations.json'
    ]
    
    # 2026-01부터 현재 달까지 모든 월별 엑셀 파일 추가
    start_year, start_month = 2026, 1
    curr_date = datetime(start_year, start_month, 1)
    while curr_date <= current_kst:
        files_to_sync.append(f'trending_integrated_{curr_date.strftime("%Y-%m")}.xlsx')
        # 다음 달로 이동
        if curr_date.month == 12:
            curr_date = datetime(curr_date.year + 1, 1, 1)
        else:
            curr_date = datetime(curr_date.year, curr_date.month + 1, 1)
    
    os.makedirs('data', exist_ok=True)
    for filename in files_to_sync:
        github_url = f"https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data/{filename}?t={int(time.time())}"
        try:
            req = urllib.request.Request(github_url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data_content = resp.read()
                # 파일 확장자에 따른 저장 방식 분기
                mode = 'wb' if filename.endswith('.xlsx') else 'w'
                final_content = data_content if filename.endswith('.xlsx') else data_content.decode('utf-8')
                
                with open(os.path.join('data', filename), mode, **({} if filename.endswith('.xlsx') else {'encoding': 'utf-8'})) as f:
                    if filename.endswith('.xlsx'): f.write(final_content)
                    else: f.write(final_content)
                print(f"[Sync] {filename} 로드 완료")
        except:
            # [Migration] 원본 파일이 없을 경우 예전 Standard 명칭 파일들 시도
            if filename == 'sim_original_state.json':
                old_files = ['sim_standard_state.json']
                target = 'sim_original_state.json'
            elif filename == 'trade_history_sim_original.csv':
                old_files = ['trade_history_sim_standard.csv']
                target = 'trade_history_sim_original.csv'
            else:
                old_files = []
                
            for old_filename in old_files:
                old_url = f"https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data/{old_filename}?t={int(time.time())}"
                try:
                    req = urllib.request.Request(old_url)
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        content = resp.read().decode('utf-8')
                        with open(os.path.join('data', target), 'w', encoding='utf-8') as f:
                            f.write(content)
                        print(f"[Sync] {old_filename}을 {target}으로 마이그레이션 완료")
                        break
                except: pass
            
            if not any(filename.startswith(f) for f in ['sim_original', 'trade_history_sim_original']):
                print(f"[Sync] {filename} 로드 실패 (파일 없음)")
        
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
                stocks = state.get('stocks', {})
                # [V8.9.9.11] 하루 단위 리포트 관리 초기화 로직
                last_date = state.get('last_update_date')
                if last_date != today_str:
                    for code, info in stocks.items():
                        yesterday_data[code] = {'consecutive_days': info.get('consecutive_days', 1), 'last_nid': info.get('last_nid')}
                    # 날짜 변경 시 모든 일일 제한 리스트 초기화
                    return {
                        'last_update_date': today_str, 
                        'stocks': {}, 
                        'reported_codes': [],           # 텔레그램 한 줄 시장 요약용 중복 방지
                        'daily_reported_info': []       # [V8.9.9.12] (이름, 코드) 페어 저장
                    }, yesterday_data
                
                # 기존 상태 로드 시 필드 누락 방지
                if 'reported_codes' not in state: state['reported_codes'] = []
                if 'daily_reported_info' not in state: state['daily_reported_info'] = []
                
                return state, yesterday_data
        except: pass
    return {
        'last_update_date': today_str, 
        'stocks': {}, 
        'reported_codes': [], 
        'reported_daily_top3': []
    }, yesterday_data

def save_sync_state(state):
    os.makedirs('data', exist_ok=True)
    with open('data/sync_state.json', 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ====================================================================
# [V8.9.9.25 Structural Fix] 독립적 연속 카운트 레지스트리 시스템
# 사용자 요청: 코드 배포나 환경 변화에 영향받지 않는 독립적 누적 체계 구축
# - data/consecutive_registry.json을 Single Source of Truth로 사용
# ====================================================================

def load_consecutive_registry():
    """연속 카운트 등록부를 로드합니다."""
    path = 'data/consecutive_registry.json'
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {"last_reset_date": "", "counts": {}}

def save_consecutive_registry(registry):
    """연속 카운트 등록부를 저장합니다."""
    os.makedirs('data', exist_ok=True)
    with open('data/consecutive_registry.json', 'w', encoding='utf-8') as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)

def update_consecutive_counts(passed_codes, now_kst):
    """
    [V8.9.9.25] 독립적 레지스트리를 기반으로 연속 카운트를 업데이트합니다.
    - 하루에 한 번만 증가하며, 포착되지 않은 날은 유지하거나 초기화 정책에 따름
    """
    registry = load_consecutive_registry()
    today_str = now_kst.strftime('%Y%m%d')
    counts = registry.get("counts", {})
    
    # 날짜가 바뀌었을 때만 업데이트 수행 (중복 실행 방지)
    if registry.get("last_reset_date") != today_str:
        print(f"[Consecutive] 날짜 변경 감지 ({registry.get('last_reset_date')} -> {today_str}). 업데이트 시작.")
        # 1. 오늘 포착된 종목은 카운트 증가
        for code in passed_codes:
            counts[code] = counts.get(code, 0) + 1
        
        # 2. 오늘 포착되지 않은 종목은 카운트 초기화 (사용자 정책: 포착 안되면 0)
        all_tracked_codes = list(counts.keys())
        for code in all_tracked_codes:
            if code not in passed_codes:
                counts[code] = 0 # 연속 등장 실패 시 초기화
        
        registry["last_reset_date"] = today_str
        registry["counts"] = counts
        save_consecutive_registry(registry)
    else:
        print(f"[Consecutive] 이미 오늘({today_str}) 업데이트가 완료되었습니다. (Skip)")
    
    return counts

def save_html_report(report_content, now_kst):
    """
    [V8.9.9.25] 제미나이 리포트를 가독성 좋은 HTML 파일로 저장합니다.
    """
    if not report_content or "[안내]" in report_content: return None
    
    os.makedirs('data/reports', exist_ok=True)
    timestamp = now_kst.strftime("%Y%m%d_%H%M%S")
    filename = f"research_report_{timestamp}.html"
    filepath = os.path.join('data/reports', filename)
    
    # HTML 템플릿 (가독성 최적화)
    html_template = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>StockBot 리서치 리포트 - {now_kst.strftime('%Y-%m-%d %H:%M')}</title>
        <style>
            body {{ font-family: 'Inter', sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 40px auto; padding: 20px; background-color: #f8f9fa; }}
            .container {{ background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            h1 {{ color: #1c7ed6; border-bottom: 2px solid #e7f5ff; padding-bottom: 10px; }}
            .date {{ color: #868e96; font-size: 0.9em; margin-bottom: 30px; }}
            .content {{ white-space: pre-wrap; font-size: 1.1em; }}
            .footer {{ margin-top: 50px; text-align: center; font-size: 0.8em; color: #adb5bd; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 StockBot 리서치 리포트</h1>
            <div class="date">발행 일시: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} KST</div>
            <div class="content">{report_content}</div>
            <div class="footer">본 리포트는 AI(Gemini 2.5 Flash)에 의해 자동 생성되었습니다.</div>
        </div>
    </body>
    </html>
    """
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html_template)
    
    # reports.json 업데이트
    update_reports_index(filename, now_kst)
    return filename

def update_reports_index(filename, now_kst):
    """reports.json 목록에 새 리포트를 추가합니다."""
    index_path = 'data/reports.json'
    reports = []
    if os.path.exists(index_path):
        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                reports = json.load(f)
        except: pass
    
    new_entry = {
        "type": "research",
        "title": f"📊 심층 분석 리포트 ({now_kst.strftime('%m/%d %H:%M')})",
        "date": now_kst.strftime("%Y-%m-%d %H:%M"),
        "filename": filename,
        "timestamp": time.time()
    }
    reports.insert(0, new_entry)
    # 최신 50개만 유지
    reports = reports[:50]
    
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(reports, f, ensure_ascii=False, indent=2)

def get_post_body(code, nid):
    """게시물의 본문 내용을 스크래핑합니다."""
    url = f"https://finance.naver.com/item/board_read.naver?code={code}&nid={nid}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.content, 'html.parser')
        body = soup.select_one('#body')
        if body:
            return body.get_text(strip=True)
    except: pass
    return ""

def get_discussion_stats(code, today_str, prev_state):
    """
    [V8.9.9.18 High-Speed Accuracy Fix]
    - 누적 합산 방식(prev + new) 폐기. 중복 오류 방지를 위해 매 실행 시 '오늘' 글 전체 재스캔
    - 중첩 병렬화(Nested Threading)로 40페이지 스캔 속도 극대화
    - today_str: '2026.04.13' 형식
    """
    headers = {'User-Agent': 'Mozilla/5.0'}
    session = requests.Session()
    session.headers.update(headers)
    
    unique_nids = set()
    new_posts = []
    
    # [Nested Parallel] 40페이지를 5페이지씩 청크로 나누어 병렬 수집
    max_pages = 40
    chunk_size = 8
    
    def fetch_page(p_idx):
        url = f"https://finance.naver.com/item/board.naver?code={code}&page={p_idx}"
        try:
            res = session.get(url, timeout=5)
            soup = BeautifulSoup(res.content, 'html.parser')
            rows = soup.select('table.type2 tr')
            page_posts = []
            stop_signal = False
            
            for row in rows:
                cols = row.select('td')
                if len(cols) < 5: continue
                
                date_text = cols[0].get_text(strip=True)
                # 오늘 날짜가 아니면 스캔 중단 신호
                if today_str not in date_text:
                    stop_signal = True
                    break

                title_tag = row.select_one('td.title a')
                if not title_tag: continue
                
                nid = re.search(r'nid=(\d+)', title_tag['href']).group(1)
                try:
                    likes = int(cols[4].get_text(strip=True))
                except: likes = 0
                
                page_posts.append({
                    'nid': nid, 
                    'title': title_tag.get_text(strip=True), 
                    'likes': likes
                })
            return page_posts, stop_signal
        except:
            return [], False

    # 페이지 묶음 단위로 스캔
    for start_p in range(1, max_pages + 1, chunk_size):
        chunk_range = range(start_p, start_p + chunk_size)
        with ThreadPoolExecutor(max_workers=chunk_size) as page_exec:
            future_to_p = {page_exec.submit(fetch_page, p): p for p in chunk_range}
            
            # 페이지 순서대로 처리하기 위해 정렬된 결과를 수합
            chunk_results = []
            for future in as_completed(future_to_p):
                res_posts, stop = future.result()
                chunk_results.append((future_to_p[future], res_posts, stop))
            
            chunk_results.sort(key=lambda x: x[0])
            
            all_stop = False
            for p_num, posts, stop in chunk_results:
                for p in posts:
                    if p['nid'] not in unique_nids:
                        unique_nids.add(p['nid'])
                        new_posts.append(p)
                if stop:
                    all_stop = True
                    break
            
            if all_stop: break

    # [V8.9.9.18] 오늘 전체 글 수 확정 (누적 방식 아님)
    total_today_count = len(unique_nids)
    latest_nid = new_posts[0]['nid'] if new_posts else None
    
    return {
        'recent_posts_count': total_today_count, 
        'new_posts': new_posts,
        'updated_state': {'cumulative_count': total_today_count, 'last_nid': latest_nid}
    }

def get_stock_details(code):
    """[V8.9.9.5] 네이버 증권 HTML 정밀 분석 및 데이터 추출 (전일 외인비중 포함)"""
    details = {
        'foreign_rate': 0.0, 
        'foreign_change': 0.0, 
        'foreign_net_buy': 0,
        'prev_close': 0,
        'prev_foreign_rate': 0.0  # [V8.9.9.5 신규] 전일 외인비중
    }
    url = f"https://finance.naver.com/item/frgn.naver?code={code}"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(res.content, 'html.parser')
        rows = soup.select('table.type2 tr')
        
        # 실제 데이터가 담긴 행만 추출 (날짜 형식이 있는 행)
        data_rows = []
        for r in rows:
            cols = r.select('td')
            if len(cols) == 9 and re.match(r'\d{4}', cols[0].get_text(strip=True)):
                data_rows.append(cols)

        if len(data_rows) >= 2:
            # 1. 외인 보유율 및 변화량
            details['foreign_rate'] = float(data_rows[0][8].get_text().replace('%','').replace(',','').strip())
            prev_rate = float(data_rows[1][8].get_text().replace('%','').replace(',','').strip())
            details['foreign_change'] = round(details['foreign_rate'] - prev_rate, 3)
            
            # 2. 외인 순매수량
            details['foreign_net_buy'] = int(data_rows[0][6].get_text().replace(',','').replace('+','').strip() or 0)
            
            # 3. 전일 종가
            details['prev_close'] = int(data_rows[1][1].get_text().replace(',','').strip() or 0)
            
            # 4. [V8.9.9.5 신규] 전일 외인비중
            details['prev_foreign_rate'] = prev_rate
            
            print(f"   [Parse Success] {code}: 외인비중 {details['foreign_rate']}% (변화 {details['foreign_change']}), 전일종가 {details['prev_close']:,}원, 전일외인 {details['prev_foreign_rate']}%")
    except Exception as e:
        print(f"   [Parse Error] {code}: {e}")
    return details

if __name__ == "__main__":
    # [V8.9.9.40] 분석 시작 시각 고정 (알림 및 파일명 기준)
    now_kst = get_current_kst_time()
    today_str = now_kst.strftime('%Y%m%d')
    start_minute = now_kst.minute
    
    print(f"[{now_kst.strftime('%Y-%m-%d %H:%M:%S')}] 🚀 StockBot Pipeline Start")
    
    # 1. 환경 변수 및 동기화 상태 로드
    load_env_manual()
    threshold = get_threshold_by_time(now_kst.hour)
    
    # 0. 모듈 초기화
    print(f"[{now_kst.strftime('%Y-%m-%d %H:%M:%S')}] 🚀 파이프라인 시퀀스 가동 (v{SCRAPER_VERSION})")
    # [V8.9.9.5 Fix] advisor는 StrategyAdvisor를 쓸 것.
    # generate_deep_dive_report, analyze_batch_discovery 메서드는 StrategyAdvisor에만 있음
    from src.strategy.advisor import StrategyAdvisor
    advisor = StrategyAdvisor()
    engine = StrategyEngine()
    tg = TelegramManager()
    sim1 = OriginalSimulator()
    sim2 = ConservativeSimulator()
    sim3 = AggressiveSimulator()
    
    # 1. 수집 및 1차 필터링
    try:
        current_candidates = analyzer.get_top_trending_stocks('KOSPI') + analyzer.get_top_trending_stocks('KOSDAQ')
        prev_sync_state, yesterday_data = load_sync_state()
        today_str = now_kst.strftime('%Y.%m.%d')
        today_date = now_kst.strftime('%Y%m%d')
        
        # ==== Stage 1: 네이버 증권 스크래핑 & 1차 필터링 ====
        print(f"[Stage 1] 네이버 토론방 데이터 수집 시작 (Thread: {threshold})")
        results = []
        print(f"[Stage 1] 후보 종목 분석 시작 (총 {len(current_candidates)}개, 병렬 엔진 가동)")
        
        def process_stock_candidate(s):
            """개별 종목 데이터를 수집하고 1차 필터링을 수행하는 내부 함수"""
            try:
                # 1. 상세 수급 및 전일 종가 수집
                d = get_stock_details(s['code'])
                s.update(d)
                
                # 2. 오늘 날짜 토론글 누적 카운트
                stats = get_discussion_stats(s['code'], today_str, prev_sync_state['stocks'])
                
                # 4. 문턱값 체크 및 통과 시 추가 데이터 수집
                if stats['recent_posts_count'] >= threshold:
                    s['recent_posts_count'] = stats['recent_posts_count']
                    all_today_posts = stats['new_posts']
                    sorted_posts = sorted(all_today_posts, key=lambda x: x['likes'], reverse=True)[:5]
                    
                    # 통과 종목만 본문 추가 수집 (여기가 병목이므로 병렬화의 이점이 큼)
                    for p in sorted_posts:
                        p['body'] = get_post_body(s['code'], p['nid'])
                    
                    s['posts'] = sorted_posts
                    return s, stats['updated_state'], True  # 통과
                
                return None, stats['updated_state'], False  # 미통과
            except Exception as e:
                print(f"   [Error] {s['name']} 스킵: {e}")
                return None, None, False

        # 1.1. [V8.9.9.27] 병렬 처리 실행
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=threshold) as executor:
            future_results = list(executor.map(process_stock_candidate, current_candidates))
            
        for res, updated_state, passed in future_results:
            if updated_state:
                prev_sync_state['stocks'].update(updated_state)
            if passed and res:
                results.append(res)
        
        # 1.5. [V8.9.9.25] 독립적 레지스트리 기반 연속 카운트 확정
        passed_codes = [s['code'] for s in results] if results else []
        final_consecutive_counts = update_consecutive_counts(passed_codes, now_kst)
        
        for s in results:
            s['consecutive_days'] = final_consecutive_counts.get(s['code'], 1)

        # 상태 영구 저장
        save_sync_state(prev_sync_state)
        print(f"[Stage 1] 수집 완료 ({len(results)}개 종목 1차 필터 통과, 문턱: {threshold})")
    except Exception as e:
        print(f"[Stage 1 Error] {e}")
        results = []

    # 2. Gemini Batch 분석
    if results:
        try:
            print(f"[Stage 2] Gemini Batch 분석 시작 (종목 수: {len(results)})")
            # 429 방어용 sleep (전략적 딜레이)
            time.sleep(2)
            batch_ai_results = advisor.analyze_batch_discovery(results)
            
            for s in results:
                code = s['code']
                # 1. 제미나이 분석 결과가 있으면 우선 적용
                if code in batch_ai_results:
                    s['sentiment_score'] = batch_ai_results[code].get('sentiment', 0)
                    s['posts_summary'] = batch_ai_results[code].get('summary', '분석 오류')
                    s['keywords'] = batch_ai_results[code].get('keywords', [])
                
                # 2. [V8.9.9.20 Fallback] 분석 결과가 누락되었거나 placeholder인 경우 데이터 기반 보완
                if s.get('posts_summary') in [None, "분석 대기중", "분석 오류", "AI 분석 불가"]:
                    kws = ", ".join(s.get('keywords', [])) if s.get('keywords') else "시장 주도주"
                    s['posts_summary'] = f"[데이터 분석] '{kws}' 중심 {s.get('recent_posts_count', 0)}건 토론 포착"
                    if not s.get('sentiment_score'): s['sentiment_score'] = 0

            print(f"[Stage 2] AI 분석 결과 적용 및 데이터 기반 보완 완료")

            # [V8.9.9.5 Recovery] 정밀 정제 로직 및 데이터 저장 강제 주입
            print(f"[Recovery] analyzer.analyze_discussion_trend 실행 중...")
            df_final, _ = analyzer.analyze_discussion_trend(results)
            analyzer.save_data(df_final)
            print(f"[Recovery] latest_stocks.json 및 status.json 저장 완료 (data/)")

        except Exception as e:
            print(f"[Stage 2 Error] AI 배치 분석 실패: {e}")

    # 3. 2차 필터(Algo04V2) 및 Deep Dive 리포트
    final_picks = []
    deep_dive_report = ""
    if results:
        try:
            # allow_buy는 장중에만
            allow_buy = 9 <= now_kst.hour < 16 and is_trading_day(now_kst)
            simulation_results = engine.execute_simulation(results, allow_buy=allow_buy)
            
            # [V8.9.9.12] 상세 리포트 중복 방지 로직 보강
            reported_already = prev_sync_state.get('reported_codes', [])
            daily_reported_info = prev_sync_state.get('daily_reported_info', []) # (이름, 코드) 리스트
            
            # 이번 턴에 뽑힌 Top 3 중에서 신규 종목들만 골라내기
            new_picks_for_report = []
            reported_codes_only = [item['code'] for item in daily_reported_info]
            
            if len(reported_codes_only) < 9:
                for r in simulation_results:
                    if r.get('signal') in ['BUY', 'WATCH'] and r['code'] not in reported_codes_only:
                        new_picks_for_report.append(r)
                        if len(reported_codes_only) + len(new_picks_for_report) >= 9:
                            break 
            
            # 최종 이번 턴의 보고 대상 (3개로 한정)
            final_picks = new_picks_for_report[:3]
            
            if final_picks:
                print(f"[Stage 3] 최종 {len(final_picks)}개 신규 종목 딥다이브 리포트 생성 중...")
                time.sleep(2)
                detail_picks = []
                for p in final_picks:
                    full_info = next((s for s in results if s['code'] == p['code']), p)
                    detail_picks.append(full_info)
                
                deep_dive_report = advisor.generate_deep_dive_report(detail_picks)
                
                # [V8.9.9.42] 월별 통합 리서치 엑셀 누적 (수익률 정보 제외 사양 반영)
                def update_monthly_research_excel(picks):
                    month_str = now_kst.strftime('%Y-%m')
                    report_dir = 'data/reports'
                    os.makedirs(report_dir, exist_ok=True)
                    target_file = f"{report_dir}/monthly_research_{month_str}.xlsx"
                    
                    new_rows = []
                    for p in picks:
                        new_rows.append({
                            'DateTime': now_kst.strftime('%Y-%m-%d %H:%M'),
                            'Stock': p['name'],
                            'Code': p['code'],
                            'Signal': p.get('signal', 'WATCH'),
                            'CurrentPrice': p.get('current_price', 0),
                            'Summary': p.get('posts_summary', '')
                        })
                    
                    new_df = pd.DataFrame(new_rows)
                    if os.path.exists(target_file):
                        try:
                            existing_df = pd.read_excel(target_file)
                            pd.concat([existing_df, new_df], ignore_index=True).to_excel(target_file, index=False)
                        except: new_df.to_excel(target_file, index=False)
                    else:
                        new_df.to_excel(target_file, index=False)
                    return target_file

                monthly_excel_path = update_monthly_research_excel(final_picks)
                print(f"[Stage 3] 월별 통합 리서치 엑셀 업데이트 완료: {monthly_excel_path}")

                # [V8.9.9.40] reports.json 관리 로직 개편 (월별 그룹화)
                def update_reports_json(filename, month_str):
                    json_path = 'data/reports.json'
                    reports = []
                    if os.path.exists(json_path):
                        try:
                            with open(json_path, 'r', encoding='utf-8') as f:
                                reports = json.load(f)
                        except: reports = []
                    
                    # 해당 월의 리서치 리포트가 이미 있는지 확인
                    title = f"📊 {month_str.split('-')[1]}월 통합 분석 리포트"
                    existing = next((r for r in reports if r.get('type') == 'research' and r.get('month') == month_str), None)
                    
                    if existing:
                        existing['title'] = title
                        existing['date'] = now_kst.strftime('%Y-%m-%d %H:%M')
                        existing['filename'] = os.path.basename(filename)
                    else:
                        reports.insert(0, {
                            "type": "research",
                            "month": month_str,
                            "title": title,
                            "date": now_kst.strftime('%Y-%m-%d %H:%M'),
                            "filename": os.path.basename(filename),
                            "timestamp": time.time()
                        })
                    
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(reports[:50], f, indent=2, ensure_ascii=False) # 최근 50개 유지

                update_reports_json(monthly_file, now_kst.strftime('%Y-%m'))
                
                # 리포트 결과 저장 및 상태 업데이트
                prev_sync_state['daily_reported_info'].extend([{'code': p['code'], 'name': p['name']} for p in final_picks])
                save_sync_state(prev_sync_state)
            elif any(r.get('signal') in ['BUY', 'WATCH'] for r in simulation_results):
                # 종목은 뽑혔으나 모두 이미 보고된 경우 명단 출력
                stock_names = [item['name'] for item in daily_reported_info]
                names_str = ", ".join(stock_names)
                dashboard_url = os.environ.get("DASHBOARD_URL", "https://stockbot-phi.vercel.app")
                deep_dive_report = f"📣 [안내] 이번 회차의 모든 top3 종목은 오늘 이미 상세 리포트가 생성되었습니다.\n\n✅ 오늘 보고된 종목: {names_str}\n\n📊 [통합 리서치 리포트 보기]\n{dashboard_url}/research"
            
        except Exception as e:
            print(f"[Stage 3 Error] 리포트 생성 실패: {e}")

    # 4. 데이터 저장, 엑셀 업데이트 및 텔레그램 전송
    if results:
        try:
            # [V8.9.9.33] 데이터 무결성 강화: 집계 전 모든 분석 데이터 강제 동기화
            print("[Stage 4] 분석 데이터 최종 정제 및 동기화 중...")
            df, _ = analyzer.analyze_discussion_trend(results)
            
            # DataFrame 결과를 results 리스트의 각 항목에 수동으로 다시 매핑 (집계 전 필수)
            for s in results:
                if s['code'] in df['code'].values:
                    row = df[df['code'] == s['code']].iloc[0]
                    s['recent_posts_count'] = int(row.get('recent_posts_count', s.get('recent_posts_count', 0)))
                    s['foreign_rate'] = float(row.get('foreign_rate', s.get('foreign_rate', 0)))
            
            # 대시보드 데이터 저장
            analyzer.save_data(df, "trending_integrated", start_time=now_kst)
            
            # [V8.9.9.33] 5일/3일 누적 보드용 데이터 집계 (데이터가 정제된 후 호출)
            os.makedirs('data', exist_ok=True)
            
            def aggregate_multi_day(days):
                filepath = f'data/analysis_{days}days.json'
                old_data_map = {}
                if os.path.exists(filepath):
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            old_list = json.load(f)
                            old_data_map = {item['code']: item for item in old_list}
                    except: pass
                
                new_aggregated = []
                for s in results:
                    old_item = old_data_map.get(s['code'], {})
                    
                    # 주가 및 토론량 배열 관리
                    spark_p = old_item.get('sparkline_price', [])
                    spark_n = old_item.get('sparkline_posts', [])
                    
                    # 오늘 데이터 추가 (KeyError 방어)
                    spark_p.append(s.get('current_price', 0))
                    spark_n.append(s.get('recent_posts_count', 0))
                    
                    s['sparkline_price'] = spark_p[-days:]
                    s['sparkline_posts'] = spark_n[-days:]
                    
                    # 평균 및 총합 계산 (스크린샷 오표기 해결)
                    if s['sparkline_posts']:
                        s['avg_posts'] = sum(s['sparkline_posts']) / len(s['sparkline_posts'])
                        s['total_posts'] = sum(s['sparkline_posts'])
                    else:
                        s['avg_posts'] = 0
                        s['total_posts'] = 0
                    
                    new_aggregated.append(s)
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(new_aggregated, f, ensure_ascii=False, indent=2)

            aggregate_multi_day(5)
            aggregate_multi_day(3)
            
            # [V8.9.9.46] 월별 통합 엑셀 리포트 누적 (수익률 제외 사양)
            def update_monthly_research_excel(new_picks, report_text):
                if not new_picks: return
                
                month_str = now_kst.strftime('%Y-%m')
                monthly_file = f"data/reports/monthly_research_{month_str}.xlsx"
                os.makedirs('data/reports', exist_ok=True)
                
                new_rows = []
                for p in new_picks:
                    new_rows.append({
                        'DateTime': now_kst.strftime('%Y-%m-%d %H:%M'),
                        'Market': p.get('market', 'Unknown'),
                        'Stock': p.get('name', 'Unknown'),
                        'Code': p.get('code', 'Unknown'),
                        'Signal': p.get('signal', 'WATCH'),
                        'Current Price': p.get('current_price', 0),
                        'Sentiment': p.get('sentiment', 'Neutral'),
                        'Key Drivers': p.get('posts_summary', '')[:100]
                    })
                
                new_df = pd.DataFrame(new_rows)
                
                try:
                    if os.path.exists(monthly_file):
                        existing_df = pd.read_excel(monthly_file)
                        final_df = pd.concat([existing_df, new_df], ignore_index=True)
                    else:
                        final_df = new_df
                    final_df.to_excel(monthly_file, index=False)
                    print(f"[Excel] 월별 통합 리포트 업데이트 완료: {monthly_file}")
                    
                    # [V8.9.9.47] UI 측 목록(reports.json) 강제 동기화
                    import glob
                    reports_list = []
                    for f_path in sorted(glob.glob('data/reports/monthly_research_*.xlsx'), reverse=True):
                        fname = os.path.basename(f_path)
                        month_part = fname.replace('monthly_research_', '').replace('.xlsx', '')
                        y, m = month_part.split('-')
                        reports_list.append({
                            "type": "research",
                            "title": f"{y}년 {int(m)}월 분석 리포트",
                            "date": now_kst.strftime('%Y-%m-%d'),
                            "filename": fname,
                            "timestamp": now_kst.timestamp()
                        })
                    with open('data/reports.json', 'w', encoding='utf-8') as rf:
                        import json
                        json.dump(reports_list, rf, ensure_ascii=False, indent=2)
                    print("[Excel] reports.json (UI 리스트) 동기화 완료")
                    
                except Exception as e:
                    print(f"[Excel Error] 월별 통합 리포트 저장 실패: {e}")

            # 리포트가 있을 경우 엑셀 업데이트 호출 (Stage 3의 final_picks 활용)
            if 'final_picks' in locals() and final_picks:
                import pandas as pd
                update_monthly_research_excel(final_picks, deep_dive_report)

            print(f"[Sync] 데이터 집계 및 엑셀 업데이트 완료")
            
            # 2. 텔레그램 발송 및 리포트 (정각 부근 또는 수동 실행 시에만)
            # [V8.9.9.22 Fix] 'repository_dispatch' 외에도 모든 스케줄링(Cron) 작업 포함
            # [V8.9.9.29 Fix] 'push' 이벤트는 알림 제외. 오직 정시 또는 수동 UI 실행 시에만.
            # [V8.9.9.40 FIX] 시작 시점의 분(start_minute)을 기준으로 알림 여부 판단 (지연 누락 방지)
            github_event = os.environ.get('GITHUB_EVENT_NAME', 'manual')
            is_manual_ui = (github_event == 'workflow_dispatch')
            is_near_the_hour = (start_minute < 5)
            
            # 매뉴얼 실행이거나 정시(0~5분)로 시작된 경우 알림
            should_send_notification = is_manual_ui or is_near_the_hour
             
            print(f"[Stage 4] 알림 조건 체크 - 이벤트: {github_event}, 현재분: {now_kst.minute}분 -> 발송여부: {should_send_notification}")
            
            if should_send_notification:
                tg.send_dashboard_link()
                
                kospi_results = [r for r in results if r.get('market') == 'KOSPI']
                kosdaq_results = [r for r in results if r.get('market') == 'KOSDAQ']
                
                if kospi_results:
                    tg.send_market_report("KOSPI 실시간 어텐션", kospi_results)
                if kosdaq_results:
                    tg.send_market_report("KOSDAQ 실시간 어텐션", kosdaq_results)
                if deep_dive_report:
                    tg.send_message(deep_dive_report)
                
                # 한 줄 요약 보고 이력(reported_codes) 업데이트 (시장 알림 중복 방지)
                # 이번 턴에 알림 나간 종목들을 기록
                all_current_results = results
                prev_sync_state['reported_codes'].extend([r['code'] for r in all_current_results if r['code'] not in reported_already])
                save_sync_state(prev_sync_state)
            else:
                print(f"[Stage 4] 현재 분({now_kst.minute}분)은 알림 미발송 구간입니다. (데이터만 축적)")
            
            # 3. 시뮬레이터 3종 트리거 (장중에만 작동)
            if allow_buy:
                print(f"[Stage 4] 시뮬레이션 3종 가동 (SIM1, SIM2, SIM3) - 주급 정합성 동기화")
                # [V8.9.9.40] 실시간 현재가 정보를 시뮬레이터에 강제 주입하여 수익률 갱신
                current_prices = {s['code']: s.get('current_price', 0) for s in results if 'code' in s}
                sim1.run(results, current_prices=current_prices)
                sim2.run(results, current_prices=current_prices)
                sim3.run(results, current_prices=current_prices)
                
                # [V8.9.9.16] 실거래 예약 주문(Reservation) 처리 엔진 가동
                try:
                    print(f"[Stage 4] 실거래 예약 주문 처리 엔진(TradeExecutor) 가동")
                    from src import trade_executor
                    trade_executor.main()
                except Exception as e:
                    print(f"[Stage 4 Error] TradeExecutor 실행 실패: {e}")
            else:
                print(f"[Stage 4] 비거래 시간대이므로 시뮬레이션 매매를 건너뜁니다.")
            
            print(f"[Stage 4] 모든 파이프라인 작업 완료")
        except Exception as e:
            print(f"[Stage 4 Error] {e}")

    print(f"[{get_current_kst_time().strftime('%Y-%m-%d %H:%M:%S')}] ✅ 모든 파이프라인 작업 완료")
