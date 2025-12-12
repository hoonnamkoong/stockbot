import requests
import io
import re
from pypdf import PdfReader

# User-Agent for download
HEADER = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# Beginner Glossary
GLOSSARY = {
    'PER': '주가수익비율(PER)은 현재 주가가 1주당 순이익의 몇 배인가를 나타냅니다. 낮을수록 저평가되었다고 봅니다.',
    'PBR': '주가순자산비율(PBR)은 주가가 순자산(자본)에 비해 몇 배로 거래되고 있는지를 보여줍니다.',
    'ROE': '자기자본이익률(ROE)은 기업이 자기자본을 활용해 얼마만큼의 이익을 냈는지 보여주는 수익성 지표입니다.',
    'TP': 'TP(Target Price)는 증권사가 예상하는 해당 주식의 목표 주가를 의미합니다.',
    'Yoy': 'YoY(Year over Year)는 전년 동기 대비 증감율을 의미합니다.',
    'Qoq': 'QoQ(Quarter over Quarter)는 직전 분기 대비 증감율을 의미합니다.'
}

def clean_pdf_text(text):
    """ Cleans extracted text, removing headers/footers/disclaimers """
    # Remove single characters standing alone (artifacts)
    text = re.sub(r'\s+.\s+', ' ', text)
    # Remove disclaimers
    if "Compliance" in text:
        text = text.split("Compliance")[0]
    return text.strip()

def download_pdf(url):
    try:
        res = requests.get(url, headers=HEADER)
        if res.status_code == 200:
            return io.BytesIO(res.content)
    except Exception as e:
        print(f"PDF Download Error: {e}")
    return None

def analyze_pdf(pdf_url):
    stream = download_pdf(pdf_url)
    if not stream: return None
    
    try:
        reader = PdfReader(stream)
        # Extract text from first 2 pages (usually sufficient for summary)
        full_text = ""
        for i in range(min(2, len(reader.pages))):
            full_text += reader.pages[i].extract_text() + "\n"
            
        if not full_text.strip():
            return {
                "opinion": "N/A",
                "target_price": "N/A",
                "summary": "텍스트 추출 불가 (이미지 스캔본일 수 있음). OCR 처리가 필요합니다."
            }

        # Parsing Logic
        cleaned_text = clean_pdf_text(full_text)
        
        # 1. Opinion
        opinion = "N/A"
        match = re.search(r'(BUY|SELL|HOLD|Reduce|매수|중립|매도)', cleaned_text, re.IGNORECASE)
        if match:
            opinion = match.group(1).upper()
            
        # 2. Target Price
        tp = "N/A"
        match_tp = re.search(r'(목표주가|Target Price|TP)\D{1,10}([\d,]+)', cleaned_text, re.IGNORECASE)
        if match_tp:
            tp = match_tp.group(2) + "원"

        # 3. Structure Extraction (Arguments)
        summary_points = []
        
        # Look for headers
        headers = ['투자포인트', 'Investment Point', '체크포인트', 'Key Charts', 'Valuation', '결론']
        sentences = cleaned_text.split('\n')
        
        capture_mode = False
        captured_lines = []
        
        for line in sentences:
            line = line.strip()
            if not line: continue
            
            # Start capturing if header found
            for h in headers:
                if h in line:
                    capture_mode = True
                    summary_points.append(f"\n[{h}]") # Add header as section
                    break
            
            if capture_mode:
                if len(captured_lines) < 10: # Limit to 10 lines of key arguments
                    captured_lines.append(line)
                    summary_points.append(f"- {line}")
            else:
                # If no header found yet, maybe check for numbered lists (1. 2. )
                if re.match(r'^[1-9]\.', line):
                    summary_points.append(f"- {line}")
        
        final_summary = "\n".join(summary_points)
        if not final_summary:
            # Fallback to first 500 chars if no structure found
            final_summary = cleaned_text[:500] + "..."

        # 4. Inject Glossary
        used_glossary = []
        for term, desc in GLOSSARY.items():
            if term in final_summary:
                used_glossary.append(f"💡 {term}: {desc}")
        
        if used_glossary:
            final_summary += "\n\n[용어 설명]\n" + "\n".join(used_glossary)

        return {
            "opinion": opinion,
            "target_price": tp,
            "summary": final_summary,
            "raw_text_snippet": cleaned_text[:200]
        }

    except Exception as e:
        print(f"PDF Parsing Error: {e}")
        return None
