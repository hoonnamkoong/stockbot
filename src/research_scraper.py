import requests
from bs4 import BeautifulSoup
import datetime
import json
import os
import re

NAVER_FINANCE_URL = "https://finance.naver.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

SECTIONS = {
    'invest': '/research/pro_invest.naver', # 시황정보
    'company': '/research/company_list.naver', # 종목분석
    'industry': '/research/industry_list.naver', # 산업분석
    'economy': '/research/economy_list.naver' # 경제분석
}

def get_headers():
    return {'User-Agent': USER_AGENT}

def fetch_section_reports(section_key):
    print(f"Fetching {url}", flush=True)
    try:
        res = requests.get(url, headers=get_headers())
        res.encoding = 'EUC-KR'
        print(f"[{section_key}] Status: {res.status_code}", flush=True)
        
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Try finding table with class 'type_1' first, then any table
        table = soup.find('table', {'class': 'type_1'})
        if not table:
            print(f"[{section_key}] 'type_1' table not found. Searching all tables...", flush=True)
            tables = soup.find_all('table')
            if not tables:
                print(f"[{section_key}] No tables found in HTML!", flush=True)
                # print(res.text[:500], flush=True) # Debug HTML
                return []
            table = tables[0] # Use the first table as fallback
            
        rows = table.find_all('tr')
        print(f"[{section_key}] Found {len(rows)} rows", flush=True)
        today_str = datetime.datetime.now().strftime("%y.%m.%d")
        
        for row in rows:
            cols = row.find_all('td')
            # Naver Research table usually has 2 empty tds for spacing, identifying real rows
            if len(cols) < 2: continue
            
            try:
                # Structure varies. Typically:
                # Company: [Company] Title | Writer | Source | PDF | Date
                # Economy: Title | Writer | Source | PDF | Date
                
                # Check Date Column (usually last or second last)
                date_node = cols[-1] # Sometimes view count is last? No, usually date.
                date_text = date_node.text.strip()
                
                # Naver date format: 25.12.12
                # If we want ONLY today's reports:
                # if date_text != today_str: continue 
                
                # Title & Link
                title_node = row.find('a', {'href': True})
                # Sometimes title is in 2nd column
                if not title_node: 
                    # Try finding in specific columns
                    for c in cols:
                         t = c.find('a', {'href': True})
                         if t and 'research' in t['href']:
                             title_node = t
                             break
                             
                if not title_node: continue
                
                link = f"{NAVER_FINANCE_URL}{title_node['href']}"
                title = title_node.text.strip()
                
                # PDF Link
                pdf_node = row.find('a', {'class': 'file'})
                pdf_link = ""
                if pdf_node:
                    pdf_link = pdf_node['href']
                    
                reports.append({
                    'title': title,
                    'link': link,
                    'date': date_text,
                    'pdf_link': pdf_link,
                    'section': section_key
                })
                
            except Exception:
                continue
                
    except Exception as e:
        print(f"Error fetching {section_key}: {e}")
        
    return reports

def fetch_all_research():
    print("Fetching Research Reports...")
    all_data = {}
    
    today_str = datetime.datetime.now().strftime("%y.%m.%d")
    
    for key in SECTIONS:
        print(f" - {key}...")
        items = fetch_section_reports(key)
        
        # Count today's items
        today_count = sum(1 for x in items if x['date'] == today_str)
        
        all_data[key] = {
            'today_count': today_count,
            'items': items[:20] # Store top 20 latest
        }
        
    return all_data

if __name__ == "__main__":
    data = fetch_all_research()
    
    os.makedirs("data", exist_ok=True)
    with open("data/latest_research.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print("Saved research data.")
