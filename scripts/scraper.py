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
# [V8.9.9.2] 데이터 정상화: 외인 변화량 계산 및 연속 일수 상태 영구 저장
SCRAPER_VERSION = "8.9.9.2 Data Recovery"

# 경로 설정
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'strategy')))
from src.strategy import analyzer
from src.strategy.advisor import StrategyAdvisor

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
    today_prefix = get_current_kst_time().strftime('%Y.%m.%d')
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
                date_text = cols[0].get_text(strip=True)
                title_tag = row.select_one('td.title a')
                if not title_tag: continue
                current_nid = re.search(r'nid=(\d+)', title_tag['href']).group(1)
                if current_nid == stock_state['last_nid']: 
                    found_prev_marker = True
                    break
                new_posts.append({'nid': current_nid, 'likes': cols[4].get_text(strip=True)})
        except: break
    total_cumulative = stock_state['cumulative_count'] + len(new_posts)
    latest_nid = new_posts[0]['nid'] if new_posts else stock_state['last_nid']
    return {'recent_posts_count': total_cumulative, 'updated_state': {'cumulative_count': total_cumulative, 'last_nid': latest_nid}}

def get_stock_details(code):
    details = {'foreign_rate': 0.0, 'foreign_change': 0.0, 'foreign_net_buy': 0}
    url = f"https://finance.naver.com/item/frgn.naver?code={code}"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        soup = BeautifulSoup(res.content, 'html.parser')
        rows = soup.select('table.type2 tr')
        data_rows = [r.select('td') for r in rows if len(r.select('td')) == 9 and re.match(r'\\d{4}', r.select('td')[0].get_text())]
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
    candidates = []
    from src.strategy import analyzer
    unique_candidates = analyzer.get_top_trending_stocks('KOSPI') + analyzer.get_top_trending_stocks('KOSDAQ')
    prev_sync_state, yesterday_data = load_sync_state()
    results = []
    for s in unique_candidates:
        d = get_stock_details(s['code'])
        s.update(d)
        stats = get_discussion_stats(s['code'], None, prev_sync_state['stocks'])
        if stats['recent_posts_count'] >= threshold:
            s['recent_posts_count'] = stats['recent_posts_count']
            results.append(s)
    if results:
        df, _ = analyzer.analyze_discussion_trend(results)
        analyzer.save_data(df, "trending_integrated")
    print("Process Finished")
