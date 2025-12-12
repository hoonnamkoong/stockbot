import requests
from bs4 import BeautifulSoup
import pandas as pd
import datetime
import time
import os
import re
import json
import collections

# --- Constants ---
NAVER_FINANCE_URL = "https://finance.naver.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# --- Helper Functions ---

def get_headers():
    return {'User-Agent': USER_AGENT}

def get_current_kst_time():
    """Returns current time in KST (UTC+9)."""
    # UTC time from GitHub Actions (or local system)
    now_utc = datetime.datetime.utcnow()
    now_kst = now_utc + datetime.timedelta(hours=9)
    return now_kst

def get_threshold_by_time(hour):
    """Returns the comment count threshold based on the hour (KST)."""
    # 10:00 run (covers 09:00 ~ 10:XX) -> Threshold 20
    if 9 <= hour < 12:
        return 20
    # 13:00 run (covers 09:00 ~ 13:XX) -> Threshold 40
    elif 12 <= hour < 14:
        return 40
    # 15:00 run (covers 09:00 ~ 15:XX) -> Threshold 60
    elif 14 <= hour < 24:
        return 60
    return 10 # Default fallback

def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

# --- 1. Fetch Trending Stocks (Volume Top) ---
def fetch_top_stocks(limit=100):
    """Fetches Top N stocks by volume from KOSPI & KOSDAQ."""
    stocks = []
    # Using 'sise_quant.naver' for Volume Top
    urls = {
        'KOSPI': f"{NAVER_FINANCE_URL}/sise/sise_quant.naver?sosok=0",
        'KOSDAQ': f"{NAVER_FINANCE_URL}/sise/sise_quant.naver?sosok=1"
    }

    print(f"Fetching Top {limit} stocks...", flush=True)

    for market, url in urls.items():
        try:
            res = requests.get(url, headers=get_headers())
            soup = BeautifulSoup(res.text, 'html.parser')
            
            table = soup.find('table', {'class': 'type_2'})
            rows = table.find_all('tr')
            
            count = 0
            for row in rows:
                cols = row.find_all('td')
                if not cols or len(cols) < 10:
                    continue
                
                try:
                    rank_node = cols[0].text.strip()
                    if not rank_node.isdigit(): continue

                    name_node = cols[1].find('a')
                    if not name_node: continue
                    
                    code = name_node['href'].split('code=')[-1]
                    name = name_node.text.strip()
                    
                    price = cols[2].text.strip().replace(',', '')
                    prev_price_raw = cols[3].text.strip().replace(',', '') # Check logic
                    rate = cols[4].text.strip()
                    volume = cols[5].text.strip()
                    
                    stocks.append({
                        'market': market,
                        'code': code,
                        'name': name,
                        'current_price': price,
                        'change_rate': rate,
                        'volume': volume
                    })
                    count += 1
                    if count >= limit // 2: # ~50 per market
                        break

                except Exception as e:
                     continue
        except Exception as e:
            print(f"Error fetching {market}: {e}", flush=True)
            
    return stocks

# --- 2. Details & Foreigner Info ---
def get_stock_details(code):
    """Fetches Foreigner ratio (Yesterday vs Today) and detailed Price."""
    url = f"{NAVER_FINANCE_URL}/item/main.naver?code={code}"
    data = {
         'foreign_ratio_today': '0%',
         'foreign_ratio_yesterday': '0%', # Hard to get exact 'yesterday' from main page without parsing charts or tables
         'yesterday_close': '0'
    }
    
    try:
        res = requests.get(url, headers=get_headers())
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 1. Foreigner Ratio (Current)
        # Assuming finding the element by text or specific ID if simpler
        # Naver HTML structure changes, but '외국인소진율' text search is robust
        
        # Helper to find sibling of text
        def find_value_by_label(label_text):
            for th in soup.find_all('th'):
                if label_text in th.text:
                    td = th.find_next_sibling('td')
                    if td: return td.text.strip()
            return None

        fr = find_value_by_label('외국인소진율')
        if fr: data['foreign_ratio_today'] = fr
        
        # Yesterday Price
        # .no_exday > .first > .blind (Yesterday)
        # But easier from the 'rate_info' section usually
        chart_area = soup.find('div', {'class': 'rate_info'})
        if chart_area:
             yesterday_tag = chart_area.find('td', {'class': 'first'})
             if yesterday_tag:
                 blind = yesterday_tag.find('span', {'class': 'blind'})
                 if blind: data['yesterday_close'] = blind.text.replace(',', '')

        # Try to find 'Yesterday Foreigner Ratio' (Approximate or Previous Day)
        # Naver Finance 'Main' page doesn't always show yesterday's ratio directly in a simple tag.
        # We will try to parse the 'Invest Info' section more deeply or just specific ID.
        # For now, we will rely on finding the 2nd value if multiple exist, or keep 0%.
        
        # Extended Logic for Yesterday Close (Check `rate_info` -> `yesterday` class)
        # <td class="first"> ... <span class="blind">12,300</span> ... </td>
        
    except Exception as e:
        pass
        
    return data

# --- 3. Board Crawling (Count & Summary) ---
def analyze_board(code, threshold=0):
    """
    Crawls board to count posts AFTER 09:00 KST today.
    Returns count, summary keywords, sentiment (mock/simple).
    """
    base_url = f"{NAVER_FINANCE_URL}/item/board.naver?code={code}"
    
    now_kst = get_current_kst_time()
    cutoff_time = now_kst.replace(hour=9, minute=0, second=0, microsecond=0)
    
    collected_titles = []
    
    page = 1
    stop_scraping = False
    
    while page <= 10 and not stop_scraping: # Max 10 pages (~200 items)
        url = f"{base_url}&page={page}"
        try:
            res = requests.get(url, headers=get_headers())
            soup = BeautifulSoup(res.text, 'html.parser')
            table = soup.find('table', {'class': 'type2'})
            if not table: break
            
            rows = table.find_all('tr')
            if len(rows) <= 2: break
            
            for row in rows:
                cols = row.find_all('td')
                if len(cols) < 6: continue
                
                date_str = cols[0].text.strip() # '2025.12.12 12:30'
                title = cols[1].text.strip()
                
                try:
                    # Parse date
                    # Naver format: YYYY.MM.DD HH:MM
                    post_dt = datetime.datetime.strptime(date_str, "%Y.%m.%d %H:%M")
                    
                    if post_dt < cutoff_time:
                        stop_scraping = True
                        break
                        
                    collected_titles.append(title)
                    
                except ValueError:
                    continue # Skip invalid dates
                    
            page += 1
            if len(collected_titles) > 300: # Safety break
                break

        except Exception:
            break
            
    # Analysis
    count = len(collected_titles)
    
    # Keyword Summary (Simple Frequency)
    words = []
    for t in collected_titles:
        words.extend(clean_text(t).split())
    
    # Filter common stopwords (very basic list)
    stopwords = ['오늘', '진짜', 'ㅋㅋ', 'ㅋㅋㅋ', 'ㅎㅎ', '결국', '근데', '지금', '어제']
    filtered_words = [w for w in words if len(w) > 1 and w not in stopwords]
    
    counter = collections.Counter(filtered_words)
    top_keywords = [k for k, v in counter.most_common(5)]
    summary = ", ".join(top_keywords) if top_keywords else "-"
    
    # Sentiment (Mock - Keyword based)
    p_score = sum(1 for w in filtered_words if w in ['상한가', '급등', '호재', '매수', '가즈아'])
    n_score = sum(1 for w in filtered_words if w in ['하한가', '폭락', '악재', '매도', '손절', '개미'])
    
    sentiment = "보통"
    if p_score > n_score: sentiment = "긍정"
    if n_score > p_score: sentiment = "부정"

    return count, summary, sentiment

# --- Main Execution ---
def main():
    print("Starting Stock Scraper...", flush=True)
    
    # 1. Time Check
    now_kst = get_current_kst_time()
    current_hour = now_kst.hour
    threshold = get_threshold_by_time(current_hour)
    
    print(f"Time (KST): {now_kst.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f"Threshold: > {threshold} posts", flush=True)
    
    # 2. Fetch Base List
    # Limit to 100 for faster check, can increase later
    candidates = fetch_top_stocks(limit=100) 
    print(f"Candidates: {len(candidates)}", flush=True)
    
    final_results = []
    
    # 3. Process Each
    for idx, stock in enumerate(candidates):
        try:
            # First, check board count (Most critical filter)
            count, summary, sentiment = analyze_board(stock['code'])
            
            if count >= threshold:
                # Met threshold! Fetch detailed info
                details = get_stock_details(stock['code'])
                stock.update(details)
                
                stock['count_today'] = count
                stock['summary'] = summary
                stock['sentiment'] = sentiment
                
                # Check consecutive logic (Mock for now, needs DB/File history)
                # In real scenario, load yesterdays CSV and check if 'code' was there.
                stock['is_consecutive'] = False 
                
                final_results.append(stock)
                print(f" [PASS] {stock['name']} ({count} posts)", flush=True)
            else:
                pass
                # print(f" [FAIL] {stock['name']} ({count} posts)")
                
        except Exception as e:
            print(f"Error processing {stock['name']}: {e}", flush=True)
            
    # 4. Save Results (ALWAYS save, even if empty)
    # Sort by Count DESC
    final_results.sort(key=lambda x: x['count_today'], reverse=True)
    
    # Save JSON
    os.makedirs("data", exist_ok=True)
    with open("data/latest_stocks.json", "w", encoding="utf-8") as f:
        json.dump(final_results, f, ensure_ascii=False, indent=2)
        
    print(f"Saved {len(final_results)} stocks to data/latest_stocks.json", flush=True)
    
    # 5. Send Telegram Notification
    if final_results:
        try:
            from utils import send_telegram_message
            
            msg = f"<b>📈 Stock Scraper Report ({now_kst.strftime('%H:%M')})</b>\n"
            msg += f"Threshold: {threshold}+\n"
            msg += f"Found: {len(final_results)} stocks\n\n"
            
            # Top 5 Summary
            for s in final_results[:5]:
                msg += f"🔥 <b>{s['name']}</b>: {s['count_today']} posts\n"
                msg += f"   (Price: {s['current_price']} | {s['change_rate']})\n"
            
            if len(final_results) > 5:
                msg += f"\n...and {len(final_results)-5} more."
                
            send_telegram_message(msg)
            
        except ImportError:
            print("Utils module not found or error importing.", flush=True)
    else:
         print("No stocks met the criteria, but saved empty list.", flush=True)

if __name__ == "__main__":
    main()
