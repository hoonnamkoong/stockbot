import requests
from io import BytesIO
import re
from pypdf import PdfReader
import pdfplumber

# User-Agent for download
HEADER = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# Beginner Glossary
GLOSSARY = {
    'PER': '주가수익비율(PER) - 낮을수록 저평가 (이익 대비 주가)',
    'PBR': '주가순자산비율(PBR) - 1 미만이면 자산가치보다 저평가',
    'ROE': '자기자본이익률(ROE) - 높을수록 효율적인 경영 (내 돈으로 번 돈)',
    'TP': 'TP(Target Price) - 증권사가 제시한 목표 주가',
    'YoY': '전년 동기 대비 증감율',
    'QoQ': '직전 분기 대비 증감율',
    'OPM': '영업이익률 (매출 대비 영업이익 비중)'
}

def clean_pdf_text(text):
    """ 
    Aggressive Cleaning for 'Insight Only' view.
    Removes: Dates, Emails, Phones, URLs, Legal Disclaimers, Headers/Footers.
    """
    if not text: return ""

    # 1. Boilerplate Removal (Compliance, Disclaimer)
    # Truncate text after common disclaimer headers
    disclaimers = ["Compliance Notice", "Compliance", "고객 여러분께", "투자 판단의 최종 책임", "본 조사분석자료", "Disclosures"]
    for d in disclaimers:
        if d in text:
            text = text.split(d)[0] # Cut off everything after disclaimer start

    # 2. Regex Cleaning
    # Remove Emails
    text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '', text)
    # Remove Phone Numbers
    text = re.sub(r'\d{2,3}[-)\.]\d{3,4}[-)\.]\d{4}', '', text)
    # Remove Dates (YYYY.MM.DD or YYYY-MM-DD) - debatable, but user asked to remove "Article Date"
    text = re.sub(r'\d{4}[\.-]\d{2}[\.-]\d{2}', '', text)
    # Remove Korean Dates (e.g., 2025년 12월 12일)
    text = re.sub(r'\d{4}년\s*\d{1,2}월\s*\d{1,2}일', '', text)
    
    # Remove URLS
    text = re.sub(r'http[s]?://\S+', '', text)
    
    # Remove Chart Axis Garbage (Sequence of numbers like "0 10 20 30 40")
    # Pattern: 2+ digits, space, 2+ digits, space, 2+ digits... repeated
    text = re.sub(r'(\b\d{1,4}\s+){3,}\d{1,4}', '', text)

    # 3. Artifact/Spacing Cleaning
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def download_pdf(url):
    try:
        res = requests.get(url, headers=HEADER, timeout=10)
        if res.status_code == 200:
            return BytesIO(res.content)
    except Exception as e:
        print(f"PDF Download Error: {e}")
    return None

def extract_tables_from_pdf(pdf_stream):
    """
    Extracts tables from the first 2 pages of the PDF using pdfplumber.
    Returns a list of Markdown-formatted tables.
    """
    markdown_tables = []
    try:
        with pdfplumber.open(pdf_stream) as pdf:
            for i, page in enumerate(pdf.pages[:2]): # Limit to first 2 pages
                tables = page.extract_tables()
                for table in tables:
                    # Filter out small/empty tables
                    if not table or len(table) < 2 or len(table[0]) < 2:
                        continue
                        
                    # Clean None values
                    cleaned_table = [[str(cell).strip() if cell else "" for cell in row] for row in table]
                    
                    # Convert to Markdown
                    # Header
                    header = "| " + " | ".join(cleaned_table[0]) + " |"
                    separator = "| " + " | ".join(["---"] * len(cleaned_table[0])) + " |"
                    body = ""
                    for row in cleaned_table[1:]:
                        body += "| " + " | ".join(row) + " |\n"
                        
                    md_table = f"{header}\n{separator}\n{body}"
                    markdown_tables.append(md_table)
    except Exception as e:
        print(f"Table Extraction Error: {e}")
        
    return markdown_tables

def analyze_pdf(pdf_url, web_body_text=""):
    """
    Analyzes PDF and optionally merges insights with Web Body Text.
    """
    stream = download_pdf(pdf_url)
    if not stream: return None
    
    # Store stream content for reuse (pdfplumber closes it?)
    # Better to create a fresh bytes object for pdfplumber since it needs a file-like object
    stream.seek(0)
    pdf_bytes = stream.read()
    stream_for_pypdf = BytesIO(pdf_bytes)
    stream_for_plumber = BytesIO(pdf_bytes)

    # 1. Text Extraction (PyPDF - Faster for text)
    full_text = ""
    try:
        reader = PdfReader(stream_for_pypdf)
        for i in range(min(2, len(reader.pages))):
            extracted = reader.pages[i].extract_text()
            if extracted: full_text += extracted + "\n"
    except Exception as e:
        print(f"PyPDF Error: {e}")

    # 2. Table Extraction (pdfplumber - Visuals)
    extracted_tables = extract_tables_from_pdf(stream_for_plumber)
    
    if not full_text.strip():
         return {
            "opinion": "N/A",
            "target_price": "N/A",
            "summary": "텍스트 추출 불가 (이미지 스캔본일 수 있음). 우측 웹 요약을 참고해주세요.",
            "tables": []
        }

    # Parsing Logic
    cleaned_text = clean_pdf_text(full_text)
    
    # ... (Rest of parsing logic for Opinion/TP/Structure) ...
    opinion = "N/A"
    match = re.search(r'(BUY|SELL|HOLD|Reduce|매수|중립|매도)', cleaned_text, re.IGNORECASE)
    if match: opinion = match.group(1).upper()
        
    tp = "N/A"
    match_tp = re.search(r'(목표주가|Target Price|TP)\D{0,10}([\d,]+)', cleaned_text, re.IGNORECASE)
    if match_tp: tp = match_tp.group(2) + "원"

    # Structure Extraction
    summary_points = []
    header_map = {
        '투자포인트': '💡 핵심 투자 포인트',
        'Investment Point': '💡 핵심 투자 포인트',
        '체크포인트': '💡 핵심 투자 포인트',
        '결론': '📌 결론',
        'Conclusion': '📌 결론',
        'Valuation': '📊 밸류에이션',
        '리스크': '⚠️ 리스크 요인'
    }
    
    sentences = cleaned_text.split('. ')
    current_section = None
    
    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 10: continue
        
        found_header = False
        for key, label in header_map.items():
            if key in sent:
                current_section = label
                summary_points.append(f"\n{current_section}")
                found_header = True
                break
        
        if not found_header and current_section:
            summary_points.append(f"- {sent}.")
            
        if len(summary_points) > 15: break
        
    final_summary = "\n".join(summary_points)
    
    if not final_summary.strip():
        if web_body_text:
            final_summary = f"[웹 본문 기반 요약]\n{web_body_text[:500]}..."
        else:
            final_summary = cleaned_text[:500] + "..."

    # Inject Glossary
    used_glossary = []
    for term, desc in GLOSSARY.items():
        if term in final_summary or term in cleaned_text:
            used_glossary.append(f"❓ {term}: {desc}")
            
    if used_glossary:
        final_summary += "\n\n📚 용어 설명:\n" + "\n".join(used_glossary)

    return {
        "opinion": opinion,
        "target_price": tp,
        "summary": final_summary,
        "tables": extracted_tables,
        "raw_text_snippet": cleaned_text[:300] + "..."
    }
