import requests
from bs4 import BeautifulSoup
import datetime
import json
import os
import re
import collections
from collections import Counter
import pdf_analyzer
import time

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

def robust_fetch_body(link):
    """
    Fetches the detail page and extracts body text using a heuristic approach.
    Strategy: Find the Title (th.view_sbj), then finding the largest text block in the same container.
    """
    try:
        log(f"   > Fetching Detail: {link}")
        res = requests.get(link, headers=get_headers())
        res.encoding = 'EUC-KR'
        soup = BeautifulSoup(res.text, 'html.parser')

        # Strategy 1: Find the 'view_sbj' TH, then look for the table, then the largest TD
        subject_th = soup.find('th', class_='view_sbj')
        if subject_th:
            # Go up to the table
            table = subject_th.find_parent('table')
            if table:
                # Find all TDs in this table
                tds = table.find_all('td')
                # Sort by text length, descending
                tds_sorted = sorted(tds, key=lambda x: len(x.get_text(strip=True)), reverse=True)
                
                if tds_sorted:
                    # The longest TD is likely the body content
                    best_match = tds_sorted[0]
                    text = best_match.get_text(separator=" ", strip=True)
                    log(f"   > Found Body Content (Length: {len(text)})")
                    return text
        
        # Strategy 2: Fallback to common classes (if strategy 1 fails)
        candidates = ['view_con', 'view_content', 'scr01']
        for cls in candidates:
            div = soup.find('div', class_=cls)
            if div:
                text = div.get_text(separator=" ", strip=True)
                log(f"   > Found Body Content via class '{cls}' (Length: {len(text)})")
                return text
                
        log("   > WARNING: Could not extract body content.")
        return ""

    except Exception as e:
        log(f"   > ERROR fetching detail: {e}")
        return ""

def summarize_text(text):
    """
    Simple extractive summarization:
    - Split into sentences.
    - Select top 5 sentences based on length and keywords.
    """
    if not text: return ""
    
    # Clean text
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Split sentences (naive)
    sentences = re.split(r'(?<=[.?!])\s+', text)
    
    unique_sentences = []
    seen = set()
    for s in sentences:
        s_clean = s.strip()
        if len(s_clean) > 20 and s_clean not in seen:
            unique_sentences.append(s_clean)
            seen.add(s_clean)
            
    # Take up to 5 sentences
    summary = " ".join(unique_sentences[:5])
    return summary

def fetch_section_reports(section_key):
    url = f"{NAVER_FINANCE_URL}{SECTIONS[section_key]}"
    log(f"--- Processing Section: {section_key} ---")
    
    reports = []
    try:
        res = requests.get(url, headers=get_headers())
        res.encoding = 'EUC-KR'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        table = soup.find('table', class_='type_1')
        if not table:
            log(f"ERROR: No table found for {section_key}")
            return []
            
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
            
            # Extract Title & Link
            title_node = row.find('a', href=True)
            if not title_node: continue
            
            title = title_node.get_text(strip=True)
            link_href = title_node['href']
            
            # Normalize Link
            if link_href.startswith('/'):
                link = f"{NAVER_FINANCE_URL}{link_href}"
            else:
                link = f"{NAVER_FINANCE_URL}/research/{link_href}" # Fallback
                
            # Extract PDF Link (CORRECTED SELECTOR)
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
    log("=== StockBot Research Scraper Started ===")
    
    all_data = {}
    today_str = datetime.datetime.now().strftime("%y.%m.%d")
    
    # 1. Collect Valid Items
    for key in SECTIONS:
        items = fetch_section_reports(key)
        
        # Filter Today
        today_items = [x for x in items if x['date'] == today_str]
        log(f"[{key}] Found {len(items)} items, {len(today_items)} from today.")
        
        # Process Today's Items (Limit to top 10 for performance)
        processed_items = []
        full_texts_for_briefing = []
        
        for i, item in enumerate(today_items[:10]):
            log(f"Processing ({i+1}/{len(today_items[:10])}): {item['title']}")
            
            # Fetch Body
            body = robust_fetch_body(item['link'])
            item['body_summary'] = summarize_text(body)
            if body:
                full_texts_for_briefing.append(body)
            
            # PDF Analysis
            if item.get('pdf_link'):
                log(f"   > Analyzing PDF: {item['pdf_link']}")
                try:
                    # Assuming pdf_analyzer.analyze_pdf works or returns None
                    pdf_result = pdf_analyzer.analyze_pdf(item['pdf_link'])
                    if pdf_result:
                        item['pdf_analysis'] = pdf_result
                        log("   > PDF Analysis Success")
                    else:
                        log("   > PDF Analysis Returned Empty")
                except Exception as e:
                    log(f"   > PDF Analysis Failed: {e}")
            
            processed_items.append(item)
            time.sleep(0.5) # Polite delay
            
        # Create Section Summary (Contextual)
        section_summary = f"오늘의 시장 키워드: {', '.join(extract_keywords(full_texts_for_briefing))}"
        
        all_data[key] = {
            'today_count': len(today_items),
            'summary': section_summary,
            'items': processed_items # Save processed items
        }

    # Save to JSON
    # Ensure directory exists
    os.makedirs('data', exist_ok=True)
    
    with open('data/latest_research.json', 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
        
    log("=== Scraper Completed Successfully ===")
    
    # Save Log
    with open('data/scraper_debug.log', 'w', encoding='utf-8') as f:
        f.write("\n".join(DEBUG_LOG))

def extract_keywords(text_list):
    """ Simple keyword extraction from a list of texts """
    if not text_list: return ["데이터 없음"]
    
    combined = " ".join(text_list)
    words = re.findall(r'\w{2,}', combined)
    
    # Filter common stopwords
    stop_words = set(['대한', '위해', '통해', '있는', '가장', '경우', '있다', '것으로', '한다', '지난', '같은'])
    words = [w for w in words if w not in stop_words]
    
    counter = Counter(words)
    return [stat[0] for stat in counter.most_common(7)]

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"CRITICAL MAIN ERROR: {e}")
        # Print log before crashing
        for l in DEBUG_LOG: print(l)
