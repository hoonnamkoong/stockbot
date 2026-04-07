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

# [V8.4.7 Gold Master] 아키텍처 안정화 버전 (휴장일 판별 및 리포트 중단 방지)
SCRAPER_VERSION = "8.4.7 Gold Master"

# 경로 설정
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src', 'strategy')))
from src.strategy import analyzer
from src.strategy.advisor import StrategyAdvisor

# --- [V8.4.4] Helper Functions ---
def get_current_kst_time():
    return datetime.utcnow() + timedelta(hours=9)

def get_threshold_by_time(hour):
    """
    [V8.5.0] 사용자 지정 일 누적 Buzz 문턱값 최종 적용
    - 00:00 ~ 08:59 : 20개
    - 00:00 ~ 10:00 : 40개
    - 00:00 ~ 13:00 : 80개
    - 00:00 ~ 15:00 : 120개
    - 이후 : 130개
    """
    if 0 <= hour < 9: return 20       # 08:59까지
    elif 9 <= hour < 11: return 40    # 10:00대까지 (10시 59분까지 포함하여 넉넉히)
    elif 11 <= hour < 14: return 80   # 13:00대까지
    elif 14 <= hour < 16: return 120  # 15:00대까지
    return 130 # 16:00 이후 최종 누적 기준

def is_trading_day(dt):
    """
    [V8.4.7] 2026년 한국거래소(KRX) 휴장일 판별 함수
    """
    # 1. 주말(토, 일)은 기본 휴장
    if dt.weekday() >= 5: return False
    
    # 2. 2026년 법정 공휴일 및 KRX 지정 휴장일
    holidays_2026 = [
        "01-01", # 신정
        "02-16", "02-17", "02-18", # 설날 연휴
        "03-01", "03-02", # 삼일절 및 대체공휴일
        "05-05", # 어린이날
        "05-22", # 부처님오신날
        "06-06", # 현충일
        "08-15", # 광복절
        "09-24", "09-25", "09-26", # 추석 연휴
        "10-03", # 개천절
        "10-09", # 한글날
        "12-25", # 성탄절
        "12-31"  # 연말 휴장일
    ]
    if dt.strftime('%m-%d') in holidays_2026: return False
    
    return True

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

def load_sync_state():
    """[V8.5.1] 종목별 당일 누적 데이터 및 마지막 게시글 ID를 로드합니다."""
    state_path = 'data/sync_state.json'
    today_str = get_current_kst_time().strftime('%Y%m%d')
    
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
                # [V8.5.1] 날짜가 바뀌었으면 리셋 (00:00 KST 기준)
                if state.get('last_update_date') != today_str:
                    print(f"[Sync] 🆕 날짜 변경 감지 ({state.get('last_update_date')} -> {today_str}) - 당일 데이터 초기화")
                    return {'last_update_date': today_str, 'stocks': {}}
                return state
        except Exception as e:
            print(f"[Sync] ⚠️ 상태 로드 실패 (초기화 진행): {e}")
            
    return {'last_update_date': today_str, 'stocks': {}}

def save_sync_state(state):
    """[V8.5.1] 갱신된 누적 데이터를 저장합니다."""
    os.makedirs('data', exist_ok=True)
    with open('data/sync_state.json', 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def extract_nid(link):
    """네이버 게시글 링크에서 고유 ID(NID)를 추출합니다."""
    match = re.search(r'nid=(\d+)', link)
    return match.group(1) if match else None

def get_discussion_stats(code, threshold_time, prev_state):
    """
    [V8.5.1] 복합 식별(NID+시간) 기반 증분 수집 알고리즘
    - 이전 실행 이후의 새 글만 수집하여 기존 누적치와 합산합니다.
    """
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    stock_state = prev_state.get(code, {'cumulative_count': 0, 'last_nid': None})
    
    new_posts = []
    today_prefix = get_current_kst_time().strftime('%Y.%m.%d')
    found_prev_marker = False
    
    # [꼼꼼한 수집] 최대 50페이지까지 훑으며 새 글 탐색
    for page in range(1, 51):
        if found_prev_marker: break
        
        url = f"https://finance.naver.com/item/board.naver?code={code}&page={page}"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code != 200: break
            soup = BeautifulSoup(res.content, 'html.parser')
            rows = soup.select('table.type2 tr')
            
            for row in rows:
                cols = row.select('td')
                if len(cols) < 5: continue
                
                date_text = cols[0].get_text(strip=True)
                if not date_text: continue
                
                # 날짜 및 시간 파싱
                try:
                    if ":" in date_text and "." not in date_text:
                        full_date = f"{today_prefix} {date_text}"
                    else:
                        full_date = date_text
                    post_date = datetime.strptime(full_date, "%Y.%m.%d %H:%M")
                except: continue
                
                # 이전 실행에서의 마지막 글을 만났는지 확인 (NID 기준)
                title_tag = row.select_one('td.title a')
                if not title_tag: continue
                
                current_nid = extract_nid(title_tag['href'])
                if current_nid == stock_state['last_nid']:
                    found_prev_marker = True
                    break
                
                # 당일 글인지 최종 확인 (장 시작 08시 이후)
                if post_date < threshold_time:
                    found_prev_marker = True
                    break
                
                new_posts.append({
                    'nid': current_nid,
                    'title': title_tag.get_text(strip=True),
                    'likes': cols[4].get_text(strip=True) if len(cols) > 4 else '0',
                    'link': title_tag['href'],
                    'time': post_date.strftime('%Y-%m-%d %H:%M')
                })
        except: break
            
    # [V8.5.1] 증분 수집 결과 계산
    new_count = len(new_posts)
    total_cumulative = stock_state['cumulative_count'] + new_count
    
    # 마지막 NID 업데이트 (수집된 글 중 가장 첫 번째 글이 최신글)
    latest_nid = new_posts[0]['nid'] if new_posts else stock_state['last_nid']
    
    # [V8.5.1] 추천수/조회수 기반 상위 5개 대표글 정렬
    # (제목 필터링 및 요약/키워드 추출의 기초 자료가 됨)
    sorted_posts = sorted(new_posts, key=lambda x: int(x['likes']) if str(x['likes']).isdigit() else 0, reverse=True)
    
    return {
        'recent_posts_count': total_cumulative, 
        'representative_posts': sorted_posts[:5], # 2단계 분석을 위한 대표글 5개
        'updated_state': {'cumulative_count': total_cumulative, 'last_nid': latest_nid}
    }

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

def process_single_stock(stock, yesterday_codes, threshold, threshold_time, prev_sync_state):
    try:
        details = get_stock_details(stock['code'])
        stock.update(details)
        
        # [V8.5.1] 누적 데이터 로드
        stats = get_discussion_stats(stock['code'], threshold_time, prev_sync_state)
        count = stats.get('recent_posts_count', 0)
        
        # [V8.4.3 로깅 강화] 통과 여부와 상관없이 수집된 원본 수 출력
        print(f"   [Buzz] {stock['name']}: {count} posts accum (Threshold: {threshold})")
        
        if count >= threshold:
            stock['recent_posts_count'] = count
            rep_posts = stats.get('representative_posts', [])
            
            # [V8.5.2] 1차 통과 종목 대상: Gemini 감정/요약/키워드 추출 (리소스 최적화)
            print(f"   [Gemini] {stock['name']} 초기 분석 중... (대표글 {len(rep_posts)}개)")
            advisor = StrategyAdvisor()
            discovery_res = advisor.analyze_initial_discovery(stock['name'], rep_posts)
            
            stock.update({
                'posts_summary': discovery_res.get('summary', '요약 실패'),
                'keywords': discovery_res.get('keywords', []),
                'sentiment_score': discovery_res.get('sentiment_score', 0),
                'is_consecutive': stock['code'] in yesterday_codes
            })
            
            # [V8.5.1] 갱신된 상태 정보를 함께 반환하도록 수정 (코드 포함)
            updated_info = stats.get('updated_state', {})
            return stock, {stock['code']: updated_info}
        return None, {stock['code']: stats.get('updated_state', {})}
    except Exception as e:
        print(f"[Error] {stock.get('name', 'Unknown')} 처리 중 오류: {e}")
        return None, None

# --- Main Flow ---
if __name__ == "__main__":
    start_time = time.perf_counter()
    load_env_manual()
    now_kst = get_current_kst_time()
    
    force_run = os.environ.get('FORCE_RUN', 'false').lower() == 'true'
    # [V8.4.7] 단순히 15시 여부를 따지지 않고 '개장일'인지 여부로 판단
    is_open_day = is_trading_day(now_kst)
    threshold = 1 if force_run else get_threshold_by_time(now_kst.hour)
    threshold_time = now_kst.replace(hour=8, minute=0, second=0, microsecond=0)
    
    print(f"[System] {SCRAPER_VERSION} 가동 (개장일: {is_open_day}, 임계값: {threshold})")

    candidates = []
    for m in ['KOSPI', 'KOSDAQ']:
        candidates.extend(analyzer.get_top_trending_stocks(m))
        candidates.extend(analyzer.get_top_rising_stocks(m))
    
    unique_candidates = list({s['code']: s for s in candidates}.values())
    print(f"[System] 유니크 후보 {len(unique_candidates)}개 수집 완료")

    yesterday_codes = set() 
    # --- 2. 1단계 Buzz Filter ---
    prev_sync_state = load_sync_state()
    current_stocks_state = prev_sync_state.get('stocks', {})
    
    results = []
    # [V8.5.1] 병렬 처리된 각 종목의 갱신된 상태를 저장할 딕셔너리
    updated_full_state = current_stocks_state.copy()

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # process_single_stock에 prev_sync_state를 전달하여 누적치 합산 수행
        futures = [executor.submit(process_single_stock, s, yesterday_codes, threshold, threshold_time, current_stocks_state) for s in unique_candidates]
        for f in concurrent.futures.as_completed(futures):
            res_stock, res_state = f.result()
            if res_state:
                # 종목별 갱신된 누적 상태(상태, 마지막 NID 등)를 병합
                updated_full_state.update(res_state) if isinstance(res_state, dict) else None
            
            if res_stock:
                results.append(res_stock)

    # 갱신된 전체 상태 저장
    prev_sync_state['stocks'] = updated_full_state
    save_sync_state(prev_sync_state)

    print(f"[System] 1단계 Buzz Filter 통과: {len(results)}개")

    # --- 3. 3차 필터링 & 심층 리뷰 (DART/뉴스) ---
    advisor_report = ""
    elite_candidates = sorted(results, key=lambda x: x.get('recent_posts_count', 0), reverse=True)[:15]
    
    if elite_candidates:
        print(f"[System] 3차 필터 통과 종목({len(elite_candidates)}개) 심층 분석 중...")
        # [V8.5.3] 최종 5개 종목에 대해 DART/뉴스 결합 리포트 생성
        final_top_5 = elite_candidates[:5]
        advisor = StrategyAdvisor()
        
        # deep_dive_report 내에서 DART/뉴스 검색 및 Gemini 리포트 생성 수행
        advisor_report = advisor.generate_deep_dive_report(final_top_5)
    else:
        advisor_report = "⚠️ 금일 분석 기준(Buzz Threshold)을 충족하는 종목이 없습니다."

    # --- 4. 알림 전송 (항상 4개 메시지 체제 유지) ---
    from src.notification.notification_service import NotificationService
    ns = NotificationService()
    
    if ns.is_available:
        # [V8.4.8] 종목 유무와 상관없이 시장 상황 보고
        kospi_items = [r for r in results if r.get('시장구분') == 'KOSPI'] or []
        kosdaq_items = [r for r in results if r.get('시장구분') == 'KOSDAQ'] or []
        
        # 실제 적용된 문턱값을 포함하여 리포트 전송
        # advisor_report가 비어있을 경우 (종목 없음) 안내 문구 삽입
        final_report_text = advisor_report if results else f"ℹ️ 현재 기준(Buzz {threshold}개)을 충족하는 종목이 없어 상세 분석이 생략되었습니다."
        
        print(f"[System] 리포트 전송 시도 (Threshold: {threshold})")
        ns.send_hourly_report(
            kospi_records=kospi_items, 
            kosdaq_records=kosdaq_items, 
            advisor_report_text=final_report_text
        )
        print("[System] 텔레그램 4세대 리포트 전송 완료")
    else:
        print("[System] 🚨 알림 서비스 비활성화 상태 (리포트 전송 스킵)")

    # --- 5. 시뮬레이션 (Virtual Only - KIS와 완전 분리) ---
    print("[System] Sandbox Simulator 가동 중...")
    from src.strategy.engine import StrategyEngine
    engine = StrategyEngine()
    # [V8.5.4] KIS 실계좌와 완전히 단절된 가상 포트폴리오 매매만 수행
    engine.execute_sandbox_simulation(results, allow_buy=force_run or is_open_day)

    elapsed = time.perf_counter() - start_time
    print(f"[System] 프로세스 종료 ({elapsed:.2f}s)")
