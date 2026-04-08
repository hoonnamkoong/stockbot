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

# [V8.9.9.5] 4단계 파이프라인 오케스트레이션 복구 버전
# [Stage 1] 수집 및 문턱 필터링 + 연속 일수 데이터 보존
# [Stage 2] Gemini 1.5 Flash-Lite 일괄(Batch) 분석
# [Stage 3] 2차 필터(Algo04V2) 및 Pro 딥다이브 리포트
# [Stage 4] 텔레그램 전송 및 시뮬레이터 트리거
SCRAPER_VERSION = "8.9.9.5 Orchestration Recovery"

# 경로 설정
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from strategy import analyzer
from strategy.advisor import StrategyAdvisor
from strategy.engine import StrategyEngine
from strategy.simulators.original_simulator import OriginalSimulator
from telegram_manager import TelegramManager

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
    for filepath in [".env", ".env.local"]:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip() and not line.startswith('#'):
                        try:
                            key, val = line.strip().split('=', 1)
                            os.environ[key.strip()] = val.strip().strip('"').strip("'")
                        except: continue

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
                    return {'last_update_date': today_str, 'stocks': {}}, yesterday_data
                return state, yesterday_data
        except: pass
    return {'last_update_date': today_str, 'stocks': {}}, yesterday_data

def save_sync_state(state):
    os.makedirs('data', exist_ok=True)
    with open('data/sync_state.json', 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def get_discussion_stats(code, threshold_time, prev_state):
    headers = {'User-Agent': 'Mozilla/5.0'}
    stock_state = prev_state.get(code, {'cumulative_count': 0, 'last_nid': None})
    new_posts = []
    found_prev_marker = False
    for page in range(1, 10):
        if found_prev_marker: break
        url = f"https://finance.naver.com/item/board.naver?code={code}&page={page}"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(res.content, 'html.parser')
            rows = soup.select('table.type2 tr')
            for row in rows:
                cols = row.select('td')
                if len(cols) < 5: continue
                title_tag = row.select_one('td.title a')
                if not title_tag: continue
                current_nid = re.search(r'nid=(\d+)', title_tag['href']).group(1)
                if current_nid == stock_state['last_nid']: 
                    found_prev_marker = True
                    break
                # API Batch 분석용 제목 수집
                new_posts.append({'nid': current_nid, 'title': title_tag.get_text(strip=True), 'likes': cols[4].get_text(strip=True)})
        except: break
    total_cumulative = stock_state['cumulative_count'] + len(new_posts)
    latest_nid = new_posts[0]['nid'] if new_posts else stock_state['last_nid']
    return {
        'recent_posts_count': total_cumulative, 
        'posts': new_posts[:10], # Batch 분석용 최신 10개 게시물
        'updated_state': {'cumulative_count': total_cumulative, 'last_nid': latest_nid}
    }

def get_stock_details(code):
    details = {'foreign_rate': 0.0, 'foreign_change': 0.0, 'foreign_net_buy': 0}
    url = f"https://finance.naver.com/item/frgn.naver?code={code}"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        soup = BeautifulSoup(res.content, 'html.parser')
        rows = soup.select('table.type2 tr')
        data_rows = [r.select('td') for r in rows if len(r.select('td')) == 9 and re.match(r'\d{4}', r.select('td')[0].get_text())]
        if len(data_rows) >= 2:
            details['foreign_rate'] = float(data_rows[0][8].get_text().replace('%',''))
            prev_rate = float(data_rows[1][8].get_text().replace('%',''))
            details['foreign_change'] = round(details['foreign_rate'] - prev_rate, 3)
            details['foreign_net_buy'] = int(data_rows[0][6].get_text().replace(',',''))
    except: pass
    return details

if __name__ == "__main__":
    load_env_manual()
    now_kst = get_current_kst_time()
    threshold = get_threshold_by_time(now_kst.hour)
    
    # 0. 모듈 초기화
    print(f"[{now_kst.strftime('%Y-%m-%d %H:%M:%S')}] 🚀 파이프라인 시퀀스 가동 (v{SCRAPER_VERSION})")
    advisor = StrategyAdvisor()
    engine = StrategyEngine()
    tg = TelegramManager()
    sim1 = OriginalSimulator()
    
    # 1. 수집 및 1차 필터링
    try:
        current_candidates = analyzer.get_top_trending_stocks('KOSPI') + analyzer.get_top_trending_stocks('KOSDAQ')
        prev_sync_state, yesterday_data = load_sync_state()
        results = []
        
        for s in current_candidates:
            d = get_stock_details(s['code'])
            s.update(d)
            stats = get_discussion_stats(s['code'], None, prev_sync_state['stocks'])
            
            # 연속 일수 업데이트
            prev_info = yesterday_data.get(s['code'], {'consecutive_days': 0})
            s['consecutive_days'] = prev_info['consecutive_days'] + 1
            
            if stats['recent_posts_count'] >= threshold:
                s['recent_posts_count'] = stats['recent_posts_count']
                s['posts'] = stats['posts']
                results.append(s)
            
            # 상태 저장용 데이터 업데이트
            prev_sync_state['stocks'][s['code']] = stats['updated_state']
            prev_sync_state['stocks'][s['code']]['consecutive_days'] = s['consecutive_days']

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
            
            # 4월 알고리즘 통과 종목 (BUY/WATCH 사유가 있는 종목 중 상위 5선)
            final_picks = [r for r in simulation_results if r.get('signal') in ['BUY', 'WATCH']][:5]
            
            if final_picks:
                print(f"[Stage 3] 최종 {len(final_picks)}개 종목 딥다이브 리포트 생성 중...")
                # 429 방어용 sleep
                time.sleep(2)
                # StrategyEngine/Advisor 연동하여 리포트 생성
                # final_picks 리스트와 원래 results의 상세 정보를 병합하여 전달
                detail_picks = []
                for p in final_picks:
                    full_info = next((s for s in results if s['code'] == p['code']), p)
                    detail_picks.append(full_info)
                
                deep_dive_report = advisor.generate_deep_dive_report(detail_picks)
                print(f"[Stage 3] 리포트 생성 완료")
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
