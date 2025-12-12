import requests
from bs4 import BeautifulSoup
import datetime
import json
import os
import re
import collections
from collections import Counter
import pdf_analyzer

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
                
                href = title_node['href']
                if not href.startswith('/'):
                    href = '/' + href
                link = f"{NAVER_FINANCE_URL}{href}"
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
        
        view_con = soup.find('div', {'class': 'view_con'})
        if view_con:
            raw_text = view_con.get_text(separator=" ", strip=True)
            
            # Simple Extractive Summarization Logic
            # 1. Split into sentences
            sentences = re.split(r'(?<=[.?!])\s+', raw_text)
            
            # 2. Keywords for scoring
            keywords = ['전망', '기대', '상향', '하향', '유지', '매수', '실적', '개선', '성장', '감소', '증가', '판단', '결론', '요약']
            
            scored_sentences = []
            for i, sent in enumerate(sentences):
                score = 0
                # Give weight to first and last sentences (often intro/conclusion)
                if i == 0: score += 2
                if i == len(sentences) - 1: score += 2
                
                # Check keywords
                for k in keywords:
                    if k in sent:
                        score += 1
                
                # Penalize too short/long noise
                if len(sent) < 10 or len(sent) > 150:
                    score -= 5
                    
                scored_sentences.append((score, i, sent))
            
            # 3. Select top 3-5 sentences
            scored_sentences.sort(key=lambda x: x[0], reverse=True)
            top_sentences = sorted(scored_sentences[:5], key=lambda x: x[1]) # Restore original order
            
            summary = " ".join([s[2] for s in top_sentences])
            return summary
            
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
        

        # Fetch Details & PDF Analysis for Top 10 Today's Items
        print(f"   Fetching details & analyzing PDF for top {min(len(today_items), 10)} items...", flush=True)
        detailed_text_for_summary = []
        pdf_summaries = []
        
        for i, item in enumerate(today_items):
            if i < 10:
                # 1. Fetch HTML Body (for Quick Look)
                body = fetch_report_details(item['link'])
                item['body_summary'] = body
                if body:
                    detailed_text_for_summary.append(body)
                
                # 2. Analyze PDF (for Deep Dive)
                if item.get('pdf_link'):
                    print(f"     Analyzing PDF for {item['title']}...", flush=True)
                    pdf_result = pdf_analyzer.analyze_pdf(item['pdf_link'])
                    if pdf_result:
                        item['pdf_analysis'] = pdf_result
                        # Add to daily briefing context
                        if pdf_result['opinion'] != 'N/A':
                            pdf_summaries.append(f"{item['title']}({pdf_result['opinion']}, TP:{pdf_result['target_price']})")
            else:
                item['body_summary'] = "요약 없음 (시간 제한)"
        
        # Improved "Daily Briefing" Generation (Sentence)
        if pdf_summaries:
            summary_text = f"오늘의 주요 리포트 분석: {', '.join(pdf_summaries[:3])} 등이 주목받고 있습니다."
            if len(pdf_summaries) > 3:
                summary_text += f" 외 {len(pdf_summaries)-3}건의 리포트가 더 있습니다."
        else:
            # Fallback to keyword summary if no PDF analysis worked
            all_text = " ".join([x['title'] for x in today_items] + detailed_text_for_summary)
            words = re.findall(r'[가-힣a-zA-Z]{2,}', all_text)
            stops = ['리포트', '투자의견', '목표가', '유지', '상향', '하향', '매수', '전망', '분석', '기준', '대비', '지속', '가능성', '예상', '실적', '증권', '투자', '발행']
            counter = collections.Counter(words)
            top_keywords = [k for k, v in counter.most_common(10) if k not in stops]
            summary_text = f"오늘의 시장 키워드: {', '.join(top_keywords[:7])} 등"

        all_data[key] = {
            'today_count': today_count,
            'summary': summary_text,
            'items': items[:40] 
        }
        
    return all_data

if __name__ == "__main__":
    data = fetch_all_research()
    
    os.makedirs("data", exist_ok=True)
    with open("data/latest_research.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print("Saved research data.")
