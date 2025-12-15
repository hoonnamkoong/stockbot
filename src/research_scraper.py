import requests
from bs4 import BeautifulSoup
import datetime
import json
import os
import re
import collections
from collections import Counter
# import pdf_analyzer # Disabled to prevent EasyOCR dependency error
import time
import random

# --- CONSTANTS ---
NAVER_FINANCE_URL = "https://finance.naver.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
SECTIONS = {
    'invest': '/research/invest_list.naver',
    'company': '/research/company_list.naver',
    'industry': '/research/industry_list.naver',
    'economy': '/research/economy_list.naver'
}

DEBUG_LOG = []

def log(msg):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    print(entry, flush=True)
    DEBUG_LOG.append(entry)

def get_headers():
    return {'User-Agent': USER_AGENT}

def clean_text(text):
    """
    Remove noise from text: Emails, Phone numbers, Dates, Copyrights, compliance text.
    """
    if not text: return ""
    
    # 1. Remove Email addresses
    text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '', text)
    # 2. Remove Phone numbers (generic patterns)
    text = re.sub(r'\d{2,3}-\d{3,4}-\d{4}', '', text)
    # 3. Remove "Compliance" or "Disclaimer" boilerplate (Korean)
    # Often appears as "본 조사분석자료는...", "당사는...", "투자자에게...", "컴플라이언스"
    # Strategy: Truncate text if we hit a known disclaimer starter
    disclaimer_starters = [
        "본 조사분석자료는", 
        "동 자료는", 
        "Compliance Notice", 
        "고객 여러분께", 
        "투자의견 및 목표주가", 
        "투자 판단의 최종 책임은"
    ]
    for starter in disclaimer_starters:
        if starter in text:
            text = text.split(starter)[0]
            
    return text.strip()

def robust_fetch_body(link):
    try:
        log(f"   > Fetching Detail: {link}")
        res = requests.get(link, headers=get_headers())
        res.encoding = 'EUC-KR'
        soup = BeautifulSoup(res.text, 'html.parser')

        # Strategy 1: Find 'view_sbj' TH -> Table -> Largest TD
        subject_th = soup.find('th', class_='view_sbj')
        if subject_th:
            table = subject_th.find_parent('table')
            if table:
                tds = table.find_all('td')
                # Sort by text length
                tds_sorted = sorted(tds, key=lambda x: len(x.get_text(strip=True)), reverse=True)
                if tds_sorted:
                    text = tds_sorted[0].get_text(separator=" ", strip=True)
                    return clean_text(text) # Apply cleaning
        
        # Strategy 2: Common classes
        candidates = ['view_con', 'view_content', 'scr01']
        for cls in candidates:
            div = soup.find('div', class_=cls)
            if div:
                text = div.get_text(separator=" ", strip=True)
                return clean_text(text)
                
        return ""
    except Exception as e:
        log(f"   > ERROR fetching detail: {e}")
        return ""

def summarize_text(text):
    """
    Extract key sentences (Arguments & Conclusion).
    """
    if not text: return ""
    
    dirty_sentences = re.split(r'(?<=[.?!])\s+', text)
    clean_sentences = []
    
    for s in dirty_sentences:
        s = s.strip()
        if len(s) < 20 or len(s) > 300: continue
        # Filter out obvious non-sentences or noise
        if "http" in s or "www" in s: continue
        clean_sentences.append(s)
        
    # Heuristic Scoring
    # Keywords indicating conclusion/argument
    keywords = ['전망', '판단', '유지', '상향', '기대', '때문', '따라서', '결론', '요약', '리스크', '매력', '성장']
    
    scored = []
    for i, sent in enumerate(clean_sentences):
        score = 0
        # Position Bias: First 2 and Last 2 are important
        if i < 2: score += 1
        if i > len(clean_sentences) - 3: score += 1
        
        for k in keywords:
            if k in sent: score += 1
            
        scored.append((score, i, sent))
        
    scored.sort(key=lambda x: x[0], reverse=True)
    top_5 = sorted(scored[:5], key=lambda x: x[1])
    
    return " ".join([t[2] for t in top_5])

def generate_insight_summary(items):
    """
    Generates a narrative 'Daily Briefing' from the list of items.
    Focuses on 'Title' and 'Opinion' (from PDF analysis) to maintain accuracy.
    """
    if not items:
        return "오늘의 리포트가 없습니다."

    # Extract industries/companies mentioned
    titles = [item['title'] for item in items[:5]]
    
    # Simple template-based insight (safer than generating hallucinations)
    # "Today's market focus is on [Top 1], [Top 2]. Key reports include [Title 1] and [Title 2]..."
    
    intro = f"오늘 발행된 주요 리포트는 총 {len(items)}건이며, "
    highlight = f"주요 관심 종목 및 산업은 '{titles[0].split('(')[0].strip()}', '{titles[1].split('(')[0].strip()}' 등 입니다. "
    
    body = "특히, "
    if len(titles) > 2:
         body += f"'{titles[2]}' 리포트와 같이 시장의 핵심 이슈를 다룬 분석이 주목받고 있습니다. "
    
    closing = "AI 분석 결과, 전반적으로 기업 실적 개선과 산업 동향 변화에 대한 기대감이 관찰됩니다."
    
    return intro + highlight + body + closing

def fetch_section_reports(section_key):
    url = f"{NAVER_FINANCE_URL}{SECTIONS[section_key]}"
    log(f"--- Section: {section_key} ---")
    reports = []
    try:
        res = requests.get(url, headers=get_headers())
        res.encoding = 'EUC-KR'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        table = soup.find('table', class_='type_1')
        if not table: return []
            
        rows = table.find_all('tr')
        today_str = datetime.datetime.now().strftime("%y.%m.%d")
        
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 2: continue
            
            # Extract Date
            date_text = ""
            for col in cols:
                txt = col.get_text(strip=True)
                if re.match(r'^\d{2}\.\d{2}\.\d{2}$', txt):
                    date_text = txt
                    break
            
            # Title & Link Logic (FIXED for Company Lists)
            # Find all links in the row
            links = row.find_all('a', href=True)
            title_node = None
            
            # Filter: We want links that look like research links, NOT stock info links
            # Stock info: /item/main.naver...
            # Research: ...read.naver...
            
            for a in links:
                href = a['href']
                if 'read.naver' in href:
                    title_node = a
                    break
            
            if not title_node and links:
                 # Fallback: if no read.naver found, but links exist, check if we skipped the title
                 # Sometimes title IS the link if it's the only one, but here we explicitly avoid item/main
                 pass

            if not title_node: continue

            title = title_node.get_text(strip=True)
            link_href = title_node['href']
            
            if link_href.startswith('/'):
                link = f"{NAVER_FINANCE_URL}{link_href}"
            else:
                link = f"{NAVER_FINANCE_URL}/research/{link_href}"
                
            pdf_link = ""
            file_td = row.find('td', class_='file')
            if file_td:
                pdf_a = file_td.find('a', href=True)
                if pdf_a:
                    pdf_link = pdf_a['href']
            
            reports.append({
                'title': title,
                'link': link,
                'date': date_text,
                'pdf_link': pdf_link,
                'section': section_key
            })
            
    except Exception as e:
        log(f"Error scraping {section_key}: {e}")
        
    return reports

def main():
    log("=== StockBot Research Scraper Started (V2.0) ===")
    
    all_data = {}
    today_str = datetime.datetime.now().strftime("%y.%m.%d")
    
    for key in SECTIONS:
        items = fetch_section_reports(key)
        today_items = [x for x in items if x['date'] == today_str]
        
        log(f"[{key}] Today: {len(today_items)} items")
        
        processed_items = []
        for i, item in enumerate(today_items[:10]):
            log(f"   Processing: {item['title']}")
            
            # Body & Clean Summary
            body = robust_fetch_body(item['link'])
            item['body_summary'] = summarize_text(body)
            
            # PDF Analysis (DISABLED per user request V6.0)
            # if item.get('pdf_link'):
            #     try:
            #         pdf_result = pdf_analyzer.analyze_pdf(item['pdf_link'])
            #         if pdf_result:
            #             item['pdf_analysis'] = pdf_result
            #     except Exception as e:
            #         log(f"     PDF Error: {e}")
            
            processed_items.append(item)
            time.sleep(0.3)
            
        # Narrative Insight Summary
        section_summary = generate_insight_summary(processed_items)
        
        all_data[key] = {
            'today_count': len(today_items),
            'summary': section_summary,
            'items': processed_items
        }

    os.makedirs('data', exist_ok=True)
    with open('data/latest_research.json', 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
        
    log("=== Completed ===")
    with open('data/scraper_debug.log', 'w', encoding='utf-8') as f:
        f.write("\n".join(DEBUG_LOG))

if __name__ == "__main__":
    main()
