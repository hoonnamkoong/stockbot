import requests
import io
import re
from pypdf import PdfReader

def download_pdf(url):
    """Downloads PDF from URL into memory."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return io.BytesIO(response.content)
    except Exception as e:
        print(f"Failed to download PDF {url}: {e}")
        return None

def extract_text_from_pdf(pdf_file, max_pages=3):
    """Extracts text from the first few pages of a PDF."""
    if not pdf_file:
        return ""
    try:
        reader = PdfReader(pdf_file)
        text = ""
        # Only read first few pages as the summary/opinion is usually there
        for i in range(min(len(reader.pages), max_pages)):
            page_text = reader.pages[i].extract_text()
            if page_text:
                text += page_text + "\n"
        return text
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return ""

def analyze_pdf(url):
    """
    Downloads and analyzes a PDF report.
    Returns a dict with:
    - opinion: "BUY", "SELL", "HOLD" etc.
    - target_price: Numeric string or "N/A"
    - summary: Extracted conclusion/summary (approx 1 page text)
    - key_points: Bullet points if found
    """
    if not url:
        return None

    pdf_file = download_pdf(url)
    full_text = extract_text_from_pdf(pdf_file)
    
    if not full_text:
        return None

    # Helpers
    def clean_text(t):
        return re.sub(r'\s+', ' ', t).strip()

    # 1. Extract Opinion
    # Pattern: "투자의견:", "Rating", "Investment Rating", "BUY", "매수"
    # This is tricky because it varies by securities firm.
    # We look for common patterns near the start.
    opinion = "N/A"
    opinion_patterns = [
        r'(?i)(?:투자의견|Rating|Investment Rating)[:\s]+(BUY|매수|Strong Buy|HOLD|중립|Marketperform|Outperform|비중확대)',
        r'(?i)(BUY|매수|HOLD|중립)(?=\s+(?:목표주가|TP|Target Price))'
    ]
    for pat in opinion_patterns:
        match = re.search(pat, full_text[:1000]) # Look in first 1000 chars
        if match:
            opinion = match.group(1).upper()
            if opinion == '매수': opinion = 'BUY'
            if opinion == '중립': opinion = 'HOLD'
            if opinion == '비중확대': opinion = 'OUTPERFORM'
            break

    # 2. Extract Target Price
    # Pattern: "목표주가", "Target Price", "TP" followed by numbers
    tp = "N/A"
    tp_patterns = [
        r'(?:목표주가|Target Price|TP)[:\s]+([\d,]+)(?:원)?',
        r'(?:목표주가|TP)\s+([\d,]+)'
    ]
    for pat in tp_patterns:
        match = re.search(pat, full_text[:1000])
        if match:
            tp = match.group(1) + "원"
            break

    # 3. Extract Summary / Conclusion (Heuristic)
    # Look for headers like "Investment Points", "Key Check", "결론", "요약"
    # Or just take the first meaningful block of text after the title info.
    summary = ""
    
    # Try to find a section header
    headers = [r'투자(?:\s*)포인트', r'투자(?:\s*)아이디어', r'Investment(?:\s*)Points?', r'Key(?:\s*)Charts?', r'Executive(?:\s*)Summary', r'체크(?:\s*)포인트', r'결론']
    
    start_idx = -1
    for h in headers:
        m = re.search(h, full_text, re.IGNORECASE)
        if m:
            start_idx = m.end()
            break
            
    if start_idx != -1:
        # Extract next 500-1000 chars
        snippet = full_text[start_idx:start_idx+1000]
        summary = clean_text(snippet)
    else:
        # Fallback: Just take text from the middle of first page (skipping headers)
        lines = full_text.split('\n')
        # Skip likely header lines (short lines, dates, company names)
        body_lines = [l for l in lines[:30] if len(l.strip()) > 30] 
        summary = " ".join(body_lines[:8]) # First 8 meaningful lines

    return {
        'opinion': opinion,
        'target_price': tp,
        'summary': summary[:800] + "..." if len(summary) > 800 else summary,
        'raw_text_snippet': full_text[:2000] # For debugging or advanced parsing
    }
