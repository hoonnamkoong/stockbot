import requests
from bs4 import BeautifulSoup
import datetime
import json
import os
import re
import collections
from collections import Counter

NAVER_FINANCE_URL = "https://finance.naver.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
SECTIONS = {
    'invest': '/research/invest_list.naver', # 투자정보 리포트
    'company': '/research/company_list.naver', # 종목분석
    'industry': '/research/industry_list.naver', # 산업분석
    'economy': '/research/economy_list.naver' # 경제분석
}

def get_headers():
    return {'User-Agent': USER_AGENT}

def fetch_section_reports(section_key):
    url = f"{NAVER_FINANCE_URL}{SECTIONS[section_key]}" # Define url here
    reports = [] # Initialize reports list
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
                
                # Find Date Column (Robust Search)
                date_text = ""
                for col in cols:
                    txt = col.text.strip()
                    # Match format 24.12.12
                    if re.match(r'^\d{2}\.\d{2}\.\d{2}$', txt):
                        date_text = txt
                        print(f"  Extracted date: {date_text}", flush=True) # Debugging log
                        break
                
                if not date_text:
                    # Fallback: Check if valid date is in the last column (sometimes)
                    # print(f"  [Skip] No date found in row", flush=True)
                    continue
                
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

def fetch_report_details(link):
    try:
        res = requests.get(link, headers=get_headers())
        res.encoding = 'EUC-KR'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Naver Research usually sends the user to a view page
        # The content is often in <div class="view_con">
        view_con = soup.find('div', {'class': 'view_con'})
        if view_con:
            text = view_con.get_text(separator=" ", strip=True)
            return text[:400] + "..." if len(text) > 400 else text
            
        return ""
    except Exception as e:
        print(f"Error fetching details for {link}: {e}")
        return ""

def fetch_all_research():
    print("Fetching Research Reports...")
    all_data = {}
    
    today_str = datetime.datetime.now().strftime("%y.%m.%d")
    
    for key in SECTIONS:
        print(f" - {key}...")
        items = fetch_section_reports(key)
        
        # Filter Today's items
        today_items = [x for x in items if x['date'] == today_str]
        today_count = len(today_items)
        
        # Fetch Details for Top 15 Today's Items (to save time)
        print(f"   Fetching details for top {min(len(today_items), 15)} items...", flush=True)
        detailed_text_for_summary = []
        
        for i, item in enumerate(today_items):
            if i < 15:
                # Fetch body content
                body = fetch_report_details(item['link'])
                item['body_summary'] = body
                if body:
                    detailed_text_for_summary.append(body)
            else:
                item['body_summary'] = "요약 없음 (시간 제한)"
        
        # Improved Keyword Extraction from BODY text
        all_text = " ".join([x['title'] for x in today_items] + detailed_text_for_summary)
        # Extract nouns (simple regex for 2+ char hangul/english)
        words = re.findall(r'[가-힣a-zA-Z]{2,}', all_text)
        
        # Stopwords
        stops = ['리포트', '투자의견', '목표가', '유지', '상향', '하향', '매수', '전망', '분석', '기준', '대비', '지속', '가능성', '예상', '실적', '증권', '투자', '발행']
        
        counter = collections.Counter(words)
        top_keywords = [k for k, v in counter.most_common(10) if k not in stops]
        summary_text = ", ".join(top_keywords[:7]) if top_keywords else "특이사항 없음"

        # Update items in the main list
        # We need to make sure 'items' list actually has the 'body_summary' updated.
        # Since 'today_items' are references to dicts in 'items', modifying them works, 
        # BUT 'items' contains all rows. We only modified the 'today' ones.
        
        all_data[key] = {
            'today_count': today_count,
            'summary': summary_text,
            'items': items[:40] # Return top 40 items total
        }
        
    return all_data

if __name__ == "__main__":
    data = fetch_all_research()
    
    os.makedirs("data", exist_ok=True)
    with open("data/latest_research.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print("Saved research data.")
