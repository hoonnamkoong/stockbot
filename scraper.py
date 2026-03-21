import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta
import time
import os
import sys
import re

# VERSION
SCRAPER_VERSION = "9.7 (Refined Schedule)"

# --- Strategy Advisor ---
from src.strategy.advisor import StrategyAdvisor

def extract_meaningful_keywords(titles, stock_name, max_keywords=5):
    STOPWORDS = {'오늘', '어제', '내일', '지금', '현재', '실시간', '속보', '주식', '종목', '매수', '매도', '투자'}
    name_parts = {stock_name}
    if len(stock_name) >= 4: name_parts.update([stock_name[:2], stock_name[2:], stock_name[:3]])
    word_freq = {}
    for title in titles:
        cleaned = re.sub(r'[^가-힣a-zA-Z0-9\s]', ' ', title)
        for word in cleaned.split():
            word = word.strip()
            if len(word) <= 1 or word.isdigit() or word in STOPWORDS: continue
            if any(part in word for part in name_parts): continue
            word_freq[word] = word_freq.get(word, 0) + 1
    return [w[0] for w in sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:max_keywords]]

def get_top_trending_stocks(market_type='KOSPI'):
    sosok = '0' if market_type == 'KOSPI' else '1'
    url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
    try:
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.content.decode('euc-kr','replace'), 'html.parser')
        rows = soup.select('table.type_2 tr')
        data = []
        for row in rows:
            cols = row.select('td')
            if len(cols) < 10: continue
            name_tag = cols[1].select_one('a')
            if not name_tag: continue
            name = name_tag.get_text(strip=True)
            if any(kw in name.upper() for kw in ['KODEX', 'TIGER']): continue
            data.append({'market': market_type, 'code': name_tag['href'].split('code=')[-1], 'name': name, 'price': int(cols[2].text.replace(',','')), 'change_rate': cols[4].text.strip()})
        return data[:35]
    except: return []

def get_stock_details(code):
    details = {}
    try:
        res = requests.get(f"https://finance.naver.com/item/frgn.naver?code={code}", timeout=10)
        soup = BeautifulSoup(res.content, 'html.parser')
        for t in soup.select('table'):
            if '외국인' in t.text and '보유율' in t.text:
                rows = [r for r in t.select('tr') if len(r.select('td')) > 5]
                if len(rows) >= 2:
                    details['foreign_rate'] = rows[0].select('td')[-1].text.strip()
                    details['prev_foreign_rate'] = rows[1].select('td')[-1].text.strip()
                    details['prev_close'] = int(rows[1].select('td')[1].text.replace(',',''))
                break
    except: pass
    return details

def get_discussion_stats(code):
    target_time = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
    collected = []
    for page in range(1, 51):
        try:
            res = requests.get(f"https://finance.naver.com/item/board.naver?code={code}&page={page}", timeout=10)
            soup = BeautifulSoup(res.content, 'html.parser')
            rows = soup.select('table.type2 tr')
            if not rows or len(collected) >= 800: break
            stop = False
            for row in rows:
                cols = row.select('td')
                if len(cols) < 5: continue
                try:
                    dt = datetime.strptime(cols[0].text.strip(), "%Y.%m.%d %H:%M")
                    if dt < target_time: {stop := True}; break
                    title_tag = row.select_one('a.title') or cols[1].select_one('a')
                    collected.append({'title': title_tag.text.strip(), 'date': cols[0].text.strip(), 'likes': cols[4].text.strip(), 'link': title_tag['href']})
                except: continue
            if stop: break
        except: break
    return {'code': code, 'recent_posts_count': len(collected), 'latest_posts': collected}

import analyzer

if __name__ == "__main__":
    now_kst = datetime.utcnow() + timedelta(hours=9)
    # --- Market Holiday Check (V9.7) ---
    import holidays
    kr_holidays = holidays.KR()
    is_weekend = now_kst.weekday() >= 5
    is_holiday = now_kst.strftime('%Y-%m-%d') in kr_holidays
    force_run = os.environ.get('FORCE_RUN', 'false').lower() == 'true'
    
    if (is_weekend or is_holiday) and not force_run:
        print(f"[System] Market Closed. Skipping execution (Use FORCE_RUN=true to bypass).")
        sys.exit(0)
    elif force_run:
        print("[System] FORCE_RUN=true detected. Bypassing market check.")

    threshold = [40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 60, 60, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100][now_kst.hour]
    all_data = []
    candidates = []
    for m in ['KOSPI', 'KOSDAQ']:
        candidates.extend(get_top_trending_stocks(m))
    
    unique_candidates = {s['code']: s for s in candidates}
    import concurrent.futures
    def process(s):
        try:
            s.update(get_stock_details(s['code']))
            stats = get_discussion_stats(s['code'])
            if stats['recent_posts_count'] >= threshold:
                s.update({'recent_posts_count': stats['recent_posts_count'], 'latest_posts': stats['latest_posts'][:10], 'scraper_version': SCRAPER_VERSION})
                return s
        except: return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        results = [f.result() for f in concurrent.futures.as_completed([ex.submit(process, s) for s in unique_candidates.values()])]
        all_data = [r for r in results if r]
    
    if all_data:
        res_df_kr, res_df_en = analyzer.analyze_discussion_trend(all_data)
        analyzer.save_data(res_df_kr, filename_prefix="trending_integrated")
        os.makedirs('data', exist_ok=True)
        with open('data/latest_stocks.json', 'w', encoding='utf-8') as f:
            import json
            json.dump(res_df_en.to_dict('records'), f, ensure_ascii=False, indent=2)

    is_top_of_hour = (0 <= now_kst.minute <= 5)
    should_send_tg = is_top_of_hour or force_run
    if all_data and should_send_tg:
        try:
            from src.telegram_manager import TelegramManager
            tm = TelegramManager()
            tm.send_message(f"🚀 <b>Stock Spike Alert</b> ({now_kst.strftime('%H:%M')})\nItems: {len(all_data)}")
        except: pass
    elif not is_top_of_hour:
        print("[System] Skipped Telegram notification window.")

    try:
        import json
        with open('data/status.json', 'w', encoding='utf-8') as f:
            json.dump({"last_updated": now_kst.strftime('%Y-%m-%d %H:%M:%S'), "count": len(all_data)}, f, ensure_ascii=False, indent=2)
    except: pass
