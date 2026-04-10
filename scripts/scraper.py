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
SCRAPER_VERSION = "8.9.9.9 Gemini 2.5 Flash Optimized"

# 경로 설정
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from src.strategy import analyzer
from src.strategy.advisor import GeminiAgent
from src.strategy.engine import StrategyEngine
from src.strategy.simulators.original_simulator import OriginalSimulator
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
    if os.path.exists(state_path):
        try:
            with open(state_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
                stocks = state.get('stocks', {})
                if state.get('last_update_date') != today_str:
                    for code, info in stocks.items():
                        yesterday_data[code] = {'consecutive_days': info.get('consecutive_days', 1), 'last_nid': info.get('last_nid')}
                    # 날짜 변경 시 reported_codes 초기화
                    return {'last_update_date': today_str, 'stocks': {}, 'reported_codes': []}, yesterday_data
                
                # 기존 상태 로드 시 필드 누락 방지
                if 'reported_codes' not in state:
                    state['reported_codes'] = []
                return state, yesterday_data
        except: pass
    return {'last_update_date': today_str, 'stocks': {}, 'reported_codes': []}, yesterday_data

def save_sync_state(state):
    os.makedirs('data', exist_ok=True)
    with open('data/sync_state.json', 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ====================================================================
# [V8.9.9.9] 연속일 별도 영구 보존 시스템
# 코드 수정/재배포 시에도 data/consecutive_days.json을 통해 값이 유지됨
# ====================================================================
CONSECUTIVE_DAYS_PATH = 'data/consecutive_days.json'

def load_consecutive_days():
    """순위 병도 consecutive_days.json에서 연속일 데이터 로드"""
    # 1. 먹저 GitHub db-data 브랜치에서 최신 데이터 다운로드 시도 (클라우드 환경)
    github_url = "https://raw.githubusercontent.com/hoonnamkoong/stockbot/db-data/data/consecutive_days.json"
    try:
        import urllib.request
        with urllib.request.urlopen(github_url, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            # 롤카운 성공 시 로컈 저장
            os.makedirs('data', exist_ok=True)
            with open(CONSECUTIVE_DAYS_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[ConsecDays] GitHub에서 {len(data)}개 종목 연속일 로드")
            return data
    except Exception as e:
        print(f"[ConsecDays] GitHub 로드 실패, 로컈 파일 시도: {e}")
    # 2. 로컈 파일 시도
    if os.path.exists(CONSECUTIVE_DAYS_PATH):
        try:
            with open(CONSECUTIVE_DAYS_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {}

def save_consecutive_days(data: dict):
    """연속일 데이터를 로컈에 저장 (db-data 브랜치로도 자동 배포됨)"""
    os.makedirs('data', exist_ok=True)
    with open(CONSECUTIVE_DAYS_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[ConsecDays] {len(data)}개 종목 연속일 저장 완료")

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
    
    # 1. 수집 및 1차 필터링
    try:
        current_candidates = analyzer.get_top_trending_stocks('KOSPI') + analyzer.get_top_trending_stocks('KOSDAQ')
        prev_sync_state, yesterday_data = load_sync_state()
        today_str = now_kst.strftime('%Y.%m.%d')
        today_date = now_kst.strftime('%Y%m%d')
        results = []
        
        # [V8.9.9.5] 연속일 영구 파일 로드
        consec_days = load_consecutive_days()
        
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
                    # [V8.9.9.5] 연속일: 영구 파일에서 박아서 +1 (코드 수정 시에도 보존)
                    prev_days_info = consec_days.get(code, {'days': 0, 'last_date': ''})
                    if prev_days_info['last_date'] == today_date:
                        # 오늘 이미 카운트된 종목
                        stock_res['consecutive_days'] = prev_days_info['days']
                    else:
                        # 새롭게 연속일 +1
                        new_days = prev_days_info['days'] + 1
                        consec_days[code] = {'days': new_days, 'last_date': today_date, 'name': stock_res.get('name', '')}
                        stock_res['consecutive_days'] = new_days
                    passed_codes.add(code)
                    print(f"   ✅ {stock_res['name']} 통과 ({stock_res['recent_posts_count']}/{threshold}), 연속 {stock_res['consecutive_days']}일")
                    results.append(stock_res)

        # [V8.9.9.5] 연속일 영구 저장 (코드좌야 날아감)
        save_consecutive_days(consec_days)
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
            
            # 4월 알고리즘 통과 종목 (BUY/WATCH 사유 종목 중 당일 중복 제외 상위 3선)
            reported_already = prev_sync_state.get('reported_codes', [])
            final_picks = [r for r in simulation_results if r.get('signal') in ['BUY', 'WATCH'] and r['code'] not in reported_already][:3]
            
            if final_picks:
                print(f"[Stage 3] 최종 {len(final_picks)}개 종목 딥다이브 리포트 생성 중...")
                # 429 방어용 sleep
                time.sleep(2)
                # StrategyEngine/Advisor 연동하여 리포트 생성
                detail_picks = []
                for p in final_picks:
                    full_info = next((s for s in results if s['code'] == p['code']), p)
                    detail_picks.append(full_info)
                
                deep_dive_report = advisor.generate_deep_dive_report(detail_picks)
                
                # [V8.9.9.9] 리포트 생성 성공 시 보고된 목록에 추가 및 상태 저장
                prev_sync_state['reported_codes'].extend([p['code'] for p in final_picks])
                save_sync_state(prev_sync_state)
                print(f"[Stage 3] 리포트 생성 완료 (오늘의 누적 보고 종목: {len(prev_sync_state['reported_codes'])}개)")
        except Exception as e:
            print(f"[Stage 3 Error] 리포트 생성 실패: {e}")

    # 4. 텔레그램 전송 및 시뮬레이터 트리거
    if results:
        try:
            # 1. 대시보드 데이터 저장 (기존 analyzer 로직 활용)
            df, _ = analyzer.analyze_discussion_trend(results)
            analyzer.save_data(df, "trending_integrated")
            
            # 2. 텔레그램 발송
            tg.send_dashboard_link()
            tg.send_market_report("KOSPI/KOSDAQ 실시간 어텐션", results)
            if deep_dive_report:
                tg.send_message(deep_dive_report)
            
            # 3. 시뮬레이터 트리거 (Sim 1: Original)
            sim1.execute_strategy(results)
            sim1.check_liquidation([s['code'] for s in results])
            
            print(f"[Stage 4] 텔레그램 전송 및 시뮬레이터 트리거 완료")
        except Exception as e:
            print(f"[Stage 4 Error] {e}")

    print(f"[{get_current_kst_time().strftime('%Y-%m-%d %H:%M:%S')}] ✅ 모든 파이프라인 작업 완료")
