
import sys
import codecs

# Force UTF-8 for stdout (fix for GitHub Actions/Windows)
sys.stdout.reconfigure(encoding='utf-8')

import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime, timedelta

def fetch_research_data():
    base_url = "https://finance.naver.com/research/"
    sections = {
        "invest": { "url": "invest_list.naver", "name": "투자정보" },
        "company": { "url": "company_list.naver", "name": "종목분석" },
        "industry": { "url": "industry_list.naver", "name": "산업분석" },
        "economy": { "url": "economy_list.naver", "name": "경제분석" }
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    today = datetime.utcnow() + timedelta(hours=9) # Strict KST
    today_str = today.strftime("%y.%m.%d") # Naver format: 25.12.10
    
    print(f"[DEBUG] Fetching research reports for {today_str} (KST)...")
    
    results = {
        "meta": {
            "date": today_str,
            "timestamp": today.strftime("%Y-%m-%d %H:%M:%S")
        }
    }
    
    for key, info in sections.items():
        url = base_url + info['url']
        try:
            res = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(res.content.decode('euc-kr', 'replace'), 'html.parser')
            
            # Table logic usually: table.type_1 or relevant
            # Titles are in td.file or similar?
            # Let's verify inspecting one.
            # Usually: div.box_type_m > table.type_1
            
            items = []
            rows = soup.select('table tr')
            
            for row in rows:
                cols = row.select('td')
                if not cols: continue
                # Layout varies but usually date is near the end.
                # Common structure: Subject | Writer | File | Date | Views
                
                # Check date first (efficient)
                # Looking for date text like '24.05.21'
                row_text = row.get_text()
                
                # Naver Research lists are often:
                # Company: 종목명 | 제목 | 적정주가 | 투자의견 | 작성자 | 제공출처 | 날짜 | 조회수
                # Others:  제목 | 작성자 | 제공출처 | 날짜 | 조회수
                
                # Let's find the date column. Usually 2nd or 3rd to last.
                # Safer: find td with class 'date' if exists, or check all cols.
                
                # Check date column (Usually near end)
                # We iterate all columns to find the exact date string
                is_today = False
                for col in cols:
                    if col.get_text(strip=True) == today_str:
                        is_today = True
                        break
                
                if is_today:
                    # Parse Data
                    links = row.select('a')
                    title = ""
                    link_url = ""

                    # Extract Key Info based on Section
                    stock_name = ""
                    category = ""
                    
                    if key == 'company' and len(cols) > 0:
                        stock_name = cols[0].get_text(strip=True)
                    elif key == 'industry' and len(cols) > 0:
                        category = cols[0].get_text(strip=True)

                    # Try to find the main report link (prioritize 'read.naver')
                    best_link = None
                    
                    for a in links:
                        href = a.get('href', '')
                        text = a.get_text(strip=True)
                        
                        if not href or not text: continue
                        if 'FileDown' in href: continue

                        # Normalize URL
                        if 'finance.naver.com' not in href:
                             if href.startswith('/'):
                                 href = "https://finance.naver.com" + href
                             elif 'read.naver' in href:
                                 href = "https://finance.naver.com/research/" + href
                        
                        # Prioritize 'read.naver' (Report Detail) over '/item/main' (Stock Info)
                        if 'read.naver' in href:
                             best_link = href
                             title = text
                             break # Found the report link!
                        
                        # Fallback (keep looking but save first candidate if nothing better found yet)
                        if not best_link and '/item/main' not in href:
                             best_link = href
                             title = text
                    
                    if best_link and title:
                        items.append({
                            "title": title,
                            "link": best_link,
                            "date": today_str,
                            "section": info['name'],
                            "stock_name": stock_name,
                            "category": category
                        })
            
            # Limit to top 5 items for detail fetching to save time/bandwidth
            print(f"  > {info['name']}: Found {len(items)} items. Fetching details for top 5...")
            
            for idx, item in enumerate(items[:5]):
                try:
                    # Detail Fetch
                    # item['link'] is already absolute URL due to previous fix
                    print(f"    Fetching details for: {item['title'][:20]}...")
                    r_detail = requests.get(item['link'], headers=headers, timeout=5)
                    s_detail = BeautifulSoup(r_detail.content.decode('euc-kr', 'replace'), 'html.parser')
                    
                    # Try to find content
                    view_content = s_detail.select_one('td.view_cnt') or s_detail.select_one('.view_cnt')
                    
                    # Try to find PDF link
                    # Common structure: <a class="stock_icon_pdf" href="..."> or check all links ending in .pdf
                    pdf_link = ""
                    for a in s_detail.select('a'):
                        href = a.get('href', '')
                        if href and href.lower().endswith('.pdf'):
                            pdf_link = href
                            print(f"Found PDF: {pdf_link}")
                            break
                            
                    if view_content:
                        # Clean text: remove script/style
                        for script in view_content(["script", "style"]):
                            script.decompose()
                        text_content = view_content.get_text(separator=' ', strip=True)
                        item['summary'] = text_content[:500] + "..." if len(text_content) > 500 else text_content
                    else:
                        item['summary'] = ""
                    
                    item['pdf_link'] = pdf_link
                        
                except Exception as e:
                    print(f"    Error fetching detail {idx}: {e}")
                    item['summary'] = ""
            
            results[key] = {
                "name": info['name'],
                "count": len(items),
                "items": items
            }

        except Exception as e:
            print(f"Error fetching {key}: {e}")
            results[key] = { "name": info['name'], "count": 0, "items": [] }

    # Save to JSON
    with open('research_latest.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print("Research data saved.")

    # Telegram Notification (Cloud/Mobile Only)
    try:
        import telegram_plugin
        import re
        from collections import Counter

        def generate_section_summary(items):
            if not items: return ""
            
            # 1. Keywords
            text_pool = " ".join([i['title'] + " " + (i.get('summary', '') or "") for i in items])
            words = re.findall(r'\w+', text_pool)
            stop_words = ['주식', '분석', '리포트', '투자의견', '목표주가', '유지', '상향', '하향', '지속', '관련', '위해', '통해', '대한', '있다', '따른', '가장', '전망', '및', '등', '것으로', '한다', '있는', '영향']
            filtered_words = [w for w in words if len(w) > 1 and w not in stop_words and not w.isdigit()]
            common_words = Counter(filtered_words).most_common(5)
            keywords_str = ", ".join([w[0] for w in common_words])
            
            # 2. Highlights (Top 3 items)
            highlights = []
            for item in items[:3]:
                # Use summary if available, else title
                content = item.get('summary', '') or item['title']
                
                # Sanitize content for Markdown (escape special chars)
                # Telegram Markdown special chars: * _ [ ] ( ) ~ ` > # + - = | { } . !
                # We simply remove blocks that often cause issues or use simple text
                
                # Extract up to 2 full sentences for better context
                sentences = re.split(r'(?<=[.?!])\s+', content)
                selected_text = ""
                for s in sentences:
                    if len(selected_text) + len(s) > 300: break 
                    selected_text += s + " "
                
                selected_text = selected_text.strip()
                if not selected_text: selected_text = content[:200]
                
                stock = f"[{item['stock_name']}] " if item.get('stock_name') else ""
                
                # User Request: Replace PDF link with Article Link
                # Use Raw URL format for reliability
                article_part = ""
                if item.get('link'):
                    article_part = f"\n   (🔗Link: {item['link']})"
                
                highlights.append(f"- {stock}{selected_text}{article_part}")
            
            summary_text = f"🔥 핵심 키워드: {keywords_str}\n"
            summary_text += "\n".join(highlights)
            return summary_text

        message = f"🔔 [오늘의 주식 리포트] {today_str}\n\n"
        
        has_content = False
        dashboard_url = os.environ.get('DASHBOARD_URL', '')

        for key, sec in results.items():
            if key == 'meta': continue
            
            if sec.get('items'):
                has_content = True
                message += f"📌 {sec['name']} 브리핑\n"
                message += generate_section_summary(sec['items'])
                message += "\n\n"
        
        if has_content:
            total_count = sum(len(s['items']) for k, s in results.items() if k != 'meta' and s.get('items'))
            message += f"👉 총 {total_count}건의 리포트가 있습니다.\n"
        else:
            message += "오늘은 등록된 신규 리포트가 없습니다.\n(휴장일이거나 아직 업데이트 전일 수 있습니다.)\n"

        if dashboard_url:
            message += f"📊 대시보드: {dashboard_url}\n"
        
        telegram_plugin.send_telegram_message(message)
            
    except Exception as e:
        print(f"Telegram notification failed (ignored in local): {e}")

    return results

if __name__ == "__main__":
    fetch_research_data()
