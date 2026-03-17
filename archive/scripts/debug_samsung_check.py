
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import sys
import os

# Mock functionality from scraper.py to isolate the issue

def get_current_kst_time():
    now_utc = datetime.utcnow()
    return now_utc + timedelta(hours=9)

def get_top_trending_stocks(market_type='KOSPI'):
    url = 'https://finance.naver.com/sise/sise_quant.naver' if market_type == 'KOSPI' else 'https://finance.naver.com/sise/sise_quant.naver?sosok=1'
    try:
        res = requests.get(url)
        soup = BeautifulSoup(res.content, 'html.parser')
        table = soup.select_one('table.type2')
        data = []
        if not table:
             print("Table not found")
             return []
             
        rows = table.select('tr')
        for row in rows:
            cols = row.select('td')
            if len(cols) < 5: continue
            try:
                name_tag = cols[1].select_one('a')
                if not name_tag: continue
                name = name_tag.get_text(strip=True)
                code = name_tag['href'].split('code=')[-1]
                data.append({'code': code, 'name': name})
            except:
                continue
        return data
    except Exception as e:
        print(f"Error fetching trending: {e}")
        return []

def get_discussion_stats(code, threshold=100):
    page = 1
    max_pages = 20
    collected = 0
    now_kst = get_current_kst_time()
    target_time = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    
    print(f"Target Time (00:00 today): {target_time}")

    while page <= max_pages:
        url = f"https://finance.naver.com/item/board.naver?code={code}&page={page}"
        try:
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(res.content, 'html.parser')
            table = soup.select_one('table.type2')
            if not table: break
            
            rows = table.select('tr')
            for row in rows:
                cols = row.select('td')
                if len(cols) < 5: continue
                
                date_text = cols[0].get_text(strip=True)
                try:
                    # Logic from scraper.py
                    post_date = datetime.strptime(date_text, "%Y.%m.%d %H:%M")
                    if post_date < target_time:
                        return collected
                except ValueError:
                    continue # Skip invalid dates
                
                collected += 1
                
            page += 1
        except Exception as e:
            print(f"Error page {page}: {e}")
            break
    return collected

if __name__ == "__main__":
    print("--- 1. Checking KOSPI List ---")
    kospi_list = get_top_trending_stocks('KOSPI')
    samsung = next((x for x in kospi_list if x['code'] == '005930'), None)
    
    if samsung:
        print(f"Samsung Electronics FOUND in list: {samsung}")
    else:
        print("Samsung Electronics NOT FOUND in KOSPI list!")
        # If not found, print top 5 to see what's there
        print(f"Top 5 found: {kospi_list[:5]}")

    print("\n--- 2. Checking Post Count for Samsung (005930) ---")
    count = get_discussion_stats('005930')
    print(f"Posts since midnight: {count}")
    
    if count >= 100:
        print("RESULT: Should have been collected (Count >= 100)")
    else:
        print("RESULT: Correctly filtered out (Count < 100)")
