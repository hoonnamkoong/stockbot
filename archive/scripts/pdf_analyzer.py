
import sys
import requests
import pdfplumber
import io
import re
import json
import os
import uuid
from bs4 import BeautifulSoup
import easyocr
import warnings

# Suppress easyocr warnings
warnings.filterwarnings("ignore")

# Configuration
MAX_REASONING_COUNT = 20
MIN_IMAGE_WIDTH = 200
MIN_IMAGE_HEIGHT = 150
IMAGE_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard", "public", "extracted_images")

# Ensure output dir exists
os.makedirs(IMAGE_OUTPUT_DIR, exist_ok=True)

# Initialize EasyOCR Reader (Korean and English)
# This might be slow on first load, but fine for backend script
# Set gpu=False for compatibility, or True if available
reader = easyocr.Reader(['ko', 'en'], gpu=False, verbose=False)

GLOSSARY = {
    # ... (Same as before)
    "PER": "주가수익비율", 
    # Truncated for brevity in replacement, assume keeping existing dictionary or I must provide full if replacing file content
    "PER": "주가수익비율(Price Earning Ratio). 현재 주가가 1주당 순이익의 몇 배인지 나타내는 지표로, 낮을수록 저평가된 것으로 봅니다.",
    "PBR": "주가순자산비율(Price Book-value Ratio). 주가가 1주당 순자산의 몇 배인지 나타내며, 1배 미만이면 자산가치보다 주가가 낮다는 뜻입니다.",
    "ROE": "자기자본이익률(Return On Equity). 기업이 자본을 이용하여 얼마만큼의 이익을 냈는지 나타내는 수익성 지표입니다.",
    "EPS": "주당순이익(Earning Per Share). 기업이 벌어들인 순이익을 주식 수로 나눈 값입니다.",
    "BPS": "주당순자산가치(Book-value Per Share). 기업의 순자산을 주식 수로 나눈 값입니다.",
    "YoY": "전년 동기 대비(Year on Year). 작년 같은 기간과 비교한 증감률입니다.",
    "QoQ": "전분기 대비(Quarter on Quarter). 직전 분기와 비교한 증감률입니다.",
    "컨센서스": "시장 전망치 평균. 여러 증권사 애널리스트들의 예상치를 평균 낸 값입니다.",
    "매수": "주식을 사는 것을 추천한다는 의미입니다.",
    "Buy": "매수(Buy). 주가 상승이 예상되므로 투자를 추천한다는 의미입니다.",
    "Hold": "보유(Hold). 주가 변동이 크지 않을 것으로 예상되니 현재 상태를 유지하라는 의미입니다.",
    "중립": "Neutral. 시장 수익률과 비슷할 것으로 예상되거나 방향성이 불확실할 때 제시합니다.",
    "비중확대": "Overweight. 포트폴리오에서 해당 주식의 비중을 늘리라는, 사실상의 매수 추천입니다.",
    "목표주가": "Target Price. 애널리스트가 기업 가치를 분석하여 적정하다고 판단한 미래의 주가입니다."
}

def fetch_post_content(post_url):
    """Fetch text content from the board post"""
    if not post_url or not post_url.startswith('http'): return ""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(post_url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Naver Finance Research Board specific selector might be needed
        # Usually it's in a specific div. Let's try generic large text blocks or specific IDs
        # For 'invest_read.naver', content is often in .view_con
        content_div = soup.select_one('.view_con')
        if content_div:
            return content_div.get_text(separator=' ', strip=True)
        else:
            # Fallback for generic structure
            return soup.get_text(separator=' ', strip=True)[:3000] 
    except Exception as e:
        # print(f"Post fetch error: {e}")
        return ""

def analyze_pdf(url, post_url=""):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        # 0. Fetch Post Content if available
        post_text = fetch_post_content(post_url)
        
        # Handle file:// URLs for local testing
        if url.startswith("http"):
            res = requests.get(url, headers=headers)
            f = io.BytesIO(res.content)
        else:
             # Assume local file path
             f = open(url, "rb")

        text_content = ""
        extracted_images = []
        ocr_text = ""
        
        with pdfplumber.open(f) as pdf:
            # Analyze only first 3 pages
            pages_to_check = pdf.pages[:3]
            for page_idx, page in enumerate(pages_to_check):
                # 1. Text Extraction
                text = page.extract_text()
                if text:
                    text_content += text + "\n"
                
                # 2. Image Extraction & OCR
                try:
                    # Find images in the page
                    for i, img in enumerate(page.images):
                        # Filter by size
                        if float(img['width']) < MIN_IMAGE_WIDTH or float(img['height']) < MIN_IMAGE_HEIGHT:
                            continue
                        
                        # Crop and save
                        bbox = (img['x0'], img['top'], img['x1'], img['bottom'])
                        cropped_page = page.crop(bbox)
                        image_obj = cropped_page.to_image(resolution=200) # Higher res for OCR
                        
                        # Save Image
                        filename = f"{uuid.uuid4()}.png"
                        filepath = os.path.join(IMAGE_OUTPUT_DIR, filename)
                        image_obj.save(filepath)
                        
                        # Run OCR
                        try:
                            # EasyOCR on the saved file or bytes
                            # reader.readtext expects file path or numpy array or bytes
                            ocr_result = reader.readtext(filepath, detail=0) 
                            if ocr_result:
                                ocr_text += " " + " ".join(ocr_result)
                        except Exception as e:
                            # print(f"OCR Error: {e}")
                            pass

                        # Add to list
                        extracted_images.append(f"/extracted_images/{filename}")
                        
                        if len(extracted_images) >= 5: break # Limit max images
                except Exception as e:
                    # print(f"Image extraction warning for page {page_idx}: {e}")
                    pass
                
            if isinstance(f, io.BytesIO): f.close()

        # Combine all texts: PDF Text + Post Text + OCR Text
        full_raw_text = text_content + "\n" + post_text + "\n" + ocr_text
        # 1. Cleaner Text
        def is_header_footer(line):
            if len(line) < 2: return True
            if re.search(r'\d{4}\.\s*\d{2}\.\s*\d{2}', line): return True
            if "리서치" in line or "Research" in line or "Analyst" in line: return True
            if "@" in line: return True
            if re.match(r'^\d+\s*$', line): return True
            return False

        def is_disclaimer(line):
            # Strict filtering for legal/compliance text
            disclaimer_keywords = [
                "무단으로", "무단 복제", "민형사상", "법적 분쟁", "증거로 사용", "참고자료로서", 
                "투자행위 결과", "책임도 지지", "Compliance Notice", "Disclaimers", 
                "통지 없이 변경", "본인의 의견을 정확하게 반영", "외부의 부당한 압력"
            ]
            for k in disclaimer_keywords:
                if k in line: return True
            return False

        def is_garbage(line):
            # Check for high density of special characters or short incoherent text
            special_chars = len(re.findall(r'[^가-힣a-zA-Z0-9\s]', line))
            if len(line) > 10 and (special_chars / len(line)) > 0.4: return True
            # Garbled text often has weird spacing like "8 관 ' 응 %"
            if len(line.split()) > len(line) / 2: return True # Too many spaces implies single chars
            return False

        lines = full_raw_text.split('\n')
        clean_lines = []
        for line in lines:
            line = line.strip()
            if len(line) <= 1: continue
            if is_header_footer(line): continue
            if is_disclaimer(line): continue
            if is_garbage(line): continue
            clean_lines.append(line)
        
        full_text = " ".join(clean_lines)

        # 2. Check for Low Text Confidence
        if len(full_text) < 50: 
            return {
                "success": True, 
                "opinion": "N/A", "target_price": "N/A",
                "reasoning": [
                    "⚠️ 텍스트 데이터가 매우 부족합니다.", 
                    "이미지 위주의 리포트이거나 스캔된 문서일 수 있습니다.", 
                    "'본문 보기'를 통해 원문을 직접 확인해주세요."
                ],
                "images": extracted_images,
                "glossary": {}
            }

        # 3. Extract Key Info
        opinion = "N/A"
        target_price = "N/A"
        
        match_opinion = re.search(r'(투자의견|Investment Opinion|Rating)[\s:]*([A-Za-z가-힣]+)', full_text[:1500], re.IGNORECASE)
        if match_opinion: opinion = match_opinion.group(2)
        else:
             match_opinion_simple = re.search(r'(Buy|Hold|Neutral|매수|중립|비중확대|Strong Buy)', full_text[:800], re.IGNORECASE)
             if match_opinion_simple: opinion = match_opinion_simple.group(1)
            
        match_tp = re.search(r'(목표주가|Target Price|TP)[\s:]*([\d,]+)\s*원', full_text[:1500], re.IGNORECASE)
        if match_tp: target_price = match_tp.group(2) + "원"

        # 4. Generate Detailed Reasoning
        reasoning_points = []
        
        # Split sentences more robustly
        raw_sentences = re.split(r'(?<=[.?!])\s+', full_text)
        sentences = []
        
        temp_s = ""
        for s in raw_sentences:
            s = s.strip()
            if not s: continue
            if len(s) < 20 and not s.endswith(('.', '!', '?')):
                 # It might be a header if short and no punctuation
                 # But here we merge generally to form sentences
                 # We will handle headers by string matching in the clean lines instead?
                 # Actually, let's just merge broadly for sentences.
                temp_s += " " + s
            else:
                sentences.append((temp_s + " " + s).strip())
                temp_s = ""
        if temp_s: sentences.append(temp_s.strip())

        
        scored_sentences = []
        keywords = ["전망", "기대", "예상", "판단", "때문", "증가", "감소", "개선", "성장", "회복", "확대", "축소", "영향", "수혜", "주목", "달성", "기록", "상회", "하회", "유지", "분석", "결과", "시사점", "포인트"]
        
        # Identify probable headers from clean_lines to boost following sentences
        # Simple heuristic: unique lines that are short and likely headers
        probable_headers = [l for l in clean_lines if len(l) < 40 and not l.endswith(('.', '다'))]
        
        for i, s in enumerate(sentences):
            s_clean = s.strip()
            if len(s_clean) < 15 or len(s_clean) > 500: continue
            
            score = 0
            
            # Keyword scoring
            for k in keywords:
                if k in s_clean: score += 1
                
            # Formatting scoring
            if re.match(r'^(\-|•|\*|\d\.)', s_clean): score += 2
            
            # Header context scoring: if previous sentence or part of this text was near a header?
            # Hard to map back to original lines exactly without complex mapping.
            # Instead, check if the sentence *contains* a header-like phrase at the start
            for ph in probable_headers:
                if s_clean.startswith(ph) and len(s_clean) > len(ph) + 10:
                    score += 2 # Boost sentences that start with a header
                    
            # Position bias: First 30% of text often has summary
            if i < len(sentences) * 0.3:
                score += 1
                
            # Penalty for likely disclaimer fragments that survived
            if any(bad in s_clean for bad in ["투자를 위한", "책임", "유가증권", "저작권"]):
                score -= 10

            if score > 0:
                scored_sentences.append((score, s_clean))
        
        # Sort by score desc
        scored_sentences.sort(key=lambda x: x[0], reverse=True)
        
        # Take up to MAX_REASONING_COUNT unique sentences
        seen = set()
        for sc, sent in scored_sentences:
            if sent not in seen:
                reasoning_points.append(sent)
                seen.add(sent)
            if len(reasoning_points) >= MAX_REASONING_COUNT: break
            
        # Fallback
        if not reasoning_points:
             for s in sentences[:10]:
                 if len(s) > 30: reasoning_points.append(s)

        # 5. Glossary
        found_terms = {}
        for term, definition in GLOSSARY.items():
            if term.lower() in full_text.lower():
                found_terms[term] = definition

        result = {
            "success": True,
            "opinion": opinion,
            "target_price": target_price,
            "reasoning": reasoning_points, 
            "images": extracted_images,
            "glossary": found_terms
        }
        
        return result

    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"success": False, "error": "No URL provided"}))
    else:
        url = sys.argv[1]
        post_url = sys.argv[2] if len(sys.argv) > 2 else ""
        print(json.dumps(analyze_pdf(url, post_url), ensure_ascii=False))
