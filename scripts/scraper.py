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

# [V8.9.9.9] Gemini 2.5 Flash + 리포트 중복 방지 최적화 버전
# [Stage 1] 수집 및 문턱 필터링 + 연속 일수 데이터 보존
# [Stage 2] Gemini 2.5 Flash 일괄(Batch) 분석 (Parsing 보강)
# [Stage 3] 2차 필터(Algo04V2) 및 Top 3 딥다이브 리포트
# [Stage 4] 텔레그램 전송 및 시뮬레이터 트리거
SCRAPER_VERSION = "8.9.9.11 Gemini 2.5 Flash Optimized (Notification Fix)"

# 경로 설정
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from src.strategy import analyzer
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
# [V8.9.9.9] 연속일 별도 영구 보존 시스템 폐기
# 사용자 요청: 코드 배포 시 json이 날아가는 문제를 방지하고자
# 5일 게시판(analyzer_5days)과 동일하게 엑셀 파일 스캐닝 방식으로 변경
# ====================================================================

def get_history_counts():
    """[V8.9.9.11] 5일 게시판(analysis_5days.json)의 연속 카운트 데이터를 직접 땡겨옵니다."""
    import urllib.request
    github_url = "https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data/analysis_5days.json"
    try:
        req = urllib.request.Request(github_url)
        # 캐시 방지 타임스탬프
        req.full_url = f"{github_url}?t={int(time.time())}"
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            history_counts = {}
            for item in data:
                code = item.get('code')
                counts = item.get('consecutive_days', 0)
                if code:
                    history_counts[str(code).zfill(6)] = counts
            print(f"[History] 5일 게시판 데이터로부터 {len(history_counts)}개 종목 이력 로드 완료")
            return history_counts
    except Exception as e:
        print(f"[Warn] 5일 게시판 히스토리 데이터 fetch 실패: {e}")
        return {}

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
    [V8.9.9.6] 오늘 날짜 기준 게시글 수 누적 및 수집
    today_str: '2026.04.09' 형식
    """
    headers = {'User-Agent': 'Mozilla/5.0'}
    stock_state = prev_state.get(code, {'cumulative_count': 0, 'last_nid': None})
    new_posts = []
    found_prev_marker = False
    stop_by_date = False

    for page in range(1, 10):
        if found_prev_marker or stop_by_date: break
        url = f"https://finance.naver.com/item/board.naver?code={code}&page={page}"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(res.content, 'html.parser')
            rows = soup.select('table.type2 tr')
            for row in rows:
                cols = row.select('td')
                if len(cols) < 5: continue
                
                # 날짜 확인 (cols[0] -> '2026.04.09 11:32')
                date_text = cols[0].get_text(strip=True)
                if today_str not in date_text:
                    # 오늘 글이 아니면 수집 중단 (누적 카운트의 정확성 보장)
                    stop_by_date = True
                    break

                title_tag = row.select_one('td.title a')
                if not title_tag: continue
                
                current_nid = re.search(r'nid=(\d+)', title_tag['href']).group(1)
                if current_nid == stock_state['last_nid']: 
                    found_prev_marker = True
                    break
                
                try:
                    likes = int(cols[4].get_text(strip=True))
                except: likes = 0
                
                new_posts.append({
                    'nid': current_nid, 
                    'title': title_tag.get_text(strip=True), 
                    'likes': likes
                })
        except: break
    
    total_cumulative = stock_state['cumulative_count'] + len(new_posts)
    latest_nid = new_posts[0]['nid'] if new_posts else stock_state['last_nid']
    
    return {
        'recent_posts_count': total_cumulative, 
        'new_posts': new_posts,
        'updated_state': {'cumulative_count': total_cumulative, 'last_nid': latest_nid}
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
    load_env_manual()
    now_kst = get_current_kst_time()
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
        history_counts = get_history_counts()
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

        # [V8.9.9.8] ThreadPoolExecutor 적용 (여유 있는 5개 스레드)
        passed_codes = set()  # 오늘 통과한 종목 코드
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_stock = {executor.submit(process_stock_candidate, s): s for s in current_candidates}
            
            for future in as_completed(future_to_stock):
                stock_res, updated_state, passed = future.result()
                s_orig = future_to_stock[future]
                code = s_orig['code']
                
                if updated_state:
                    prev_sync_state['stocks'][code] = updated_state
                
                if passed and stock_res:
                    # [V8.9.9.5 User Request] 연속일 수는 5일 게시판처럼 저장된 엑셀 데이터를 스캔하여 확정
                    # 만약 오늘 오전에 이미 스크래핑이 돌아 엑셀에 존재한다면 거기서 카운트 1이 더해졌을 수 있으므로 1을 최솟값으로 잡고 덧셈
                    # (히스토리에 없으면 1일차)
                    past_appearances = history_counts.get(code, 0)
                    # 오늘 처음 포착된 것이면 past_appearances가 0일 수 있으므로 (또는 당일 파일에 없으면)
                    # 최솟값 1은 보장
                    new_days = past_appearances + 1
                            
                    stock_res['consecutive_days'] = new_days
                    passed_codes.add(code)
                    print(f"   ✅ {stock_res['name']} 통과 ({stock_res['recent_posts_count']}/{threshold}), 엑셀조회 연속 {stock_res['consecutive_days']}일")
                    results.append(stock_res)

        # 상태 영구 저장 (consec_days json은 사용성 폐기)
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
                if code in batch_ai_results:
                    s['sentiment_score'] = batch_ai_results[code].get('sentiment', 0)
                    s['posts_summary'] = batch_ai_results[code].get('summary', '분석 오류')
                    s['keywords'] = batch_ai_results[code].get('keywords', [])
            print(f"[Stage 2] AI 배치 분석 완료")

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
                
                # 리포트 결과 저장 및 상태 업데이트
                prev_sync_state['daily_reported_info'].extend([{'code': p['code'], 'name': p['name']} for p in final_picks])
                save_sync_state(prev_sync_state)
            elif any(r.get('signal') in ['BUY', 'WATCH'] for r in simulation_results):
                # 종목은 뽑혔으나 모두 이미 보고된 경우 명단 출력
                stock_names = [item['name'] for item in daily_reported_info]
                names_str = ", ".join(stock_names)
                deep_dive_report = f"📣 [안내] 이번 회차의 모든 top3 종목은 오늘 이미 상세 리포트가 생성되었습니다.\n\n✅ 오늘 보고된 종목: {names_str}"
            
        except Exception as e:
            print(f"[Stage 3 Error] 리포트 생성 실패: {e}")

    # 4. 텔레그램 전송 및 시뮬레이터 트리거
    if results:
        try:
            # 1. 대시보드 데이터 저장 (기존 analyzer 로직 활용)
            # [V8.9.9.11] scraper 기동 시각(now_kst)을 analyzer에 전달하여 status.json 시간 고정
            df, _ = analyzer.analyze_discussion_trend(results)
            analyzer.save_data(df, "trending_integrated", start_time=now_kst)
            
            # 2. 텔레그램 발송 및 리포트 (정각 부근 또는 수동 실행 시에만)
            github_event = os.environ.get('GITHUB_EVENT_NAME', 'manual')
            is_scheduled = (github_event == 'repository_dispatch')
            is_near_the_hour = (now_kst.minute < 10)
            is_manual_event = (github_event in ['workflow_dispatch', 'push', 'manual'])
            
            if (is_scheduled and is_near_the_hour) or (not is_scheduled) or is_manual_event:
                print(f"[Stage 4] 알림 조건 충족 (이벤트:{github_event}, 정각부근:{is_near_the_hour}) -> 발송 시작")
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
                print(f"[Stage 4] 시뮬레이션 3종 가동 (SIM1, SIM2, SIM3)")
                sim1.run(results)
                sim2.run(results)
                sim3.run(results)
                
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
