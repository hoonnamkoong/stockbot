
import re

STOPWORDS = {
    '오늘', '어제', '내일', '지금', '현재', '실시간', '속보', '긴급',
    '주식', '종목', '매수', '매도', '매매', '투자', '주가', '가격',
    '상한가', '하한가', '급등', '급락', '폭등', '폭락', '상승', '하락',
    '정보', '분석', '전망', '예상', '의견', '생각', '질문', '궁금',
    '여기', '저기', '이거', '저거', '그거', '뭐', '왜', '어떻게',
    '진짜', '정말', '완전', '너무', '진심', '대박', '헐', '와',
    '사람', '분들', '여러분', '우리', '나', '제가', '내가',
    '합니다', '입니다', '습니다', '됩니다', '같습니다', '봅니다',
    '하는', '것', '수', '중', '후', '전', '때', '더', '안', '못',
    '좀', '잘', '다', '또', '그냥', '아직', '이미', '계속', '다시',
    '보세요', '하세요', '드립니다', '감사', '부탁', '제발',
    '코스피', '코스닥', 'KOSPI', 'KOSDAQ',
    '원', '만원', '천원', '억', '조', '퍼센트',
    '오늘도', '오늘은', '어제도', '내일도', '지금은', '현재가', '목표가', '매수가', '매도가',
    'ㅋㅋ', 'ㅋㅋㅋ', 'ㅋㅋㅋㅋ', 'ㅎㅎ', 'ㅎㅎㅎ', 'ㄷㄷ', 'ㄷㄷㄷ',
    '공시', '뉴스', '속보', '특징주', '단독', '상보', '종합', '오후', '오전'
}

def extract_meaningful_keywords(titles, stock_name, max_keywords=5):
    # Break stock name into parts
    name_parts = set()
    name_parts.add(stock_name)
    if len(stock_name) >= 4:
        name_parts.add(stock_name[:2])
        name_parts.add(stock_name[2:])
        name_parts.add(stock_name[:3])
    
    print(f"DEBUG: Stock Name Parts for {stock_name}: {name_parts}")

    word_freq = {}
    for title in titles:
        # Remove special chars
        cleaned = re.sub(r'[^가-힣a-zA-Z0-9\s]', ' ', title)
        words = cleaned.split()
        
        for word in words:
            original_word = word
            word = word.strip()
            
            # Debug specific words
            if '오늘' in word or '공시' in word:
                print(f"DEBUG Check '{word}': In STOPWORDS? {word in STOPWORDS}")
            
            if len(word) <= 1: continue
            if word.isdigit(): continue
            if word in STOPWORDS or word.lower() in STOPWORDS: continue
            
            # Name check
            is_name_part = False
            for part in name_parts:
                if part in word:
                    is_name_part = True
                    break
            if is_name_part: continue

            # Verb heuristic
            if word.endswith('다') or word.endswith('요') or word.endswith('까') or word.endswith('죠') or word.endswith('임') or word.endswith('함'):
                print(f"DEBUG: Filtered verb '{word}'")
                continue

            if len(set(word)) == 1: continue
            
            word_freq[word] = word_freq.get(word, 0) + 1

    sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
    return [w[0] for w in sorted_words[:max_keywords]]

# Test Case
titles = [
    "오늘 공시 떴다 대박",
    "오늘도 삼성전자 오르나요",
    "비엘팜텍 오늘 공시 분석",
    "특징주 속보 떴음"
]
result = extract_meaningful_keywords(titles, "비엘팜텍")
print(f"Result for 비엘팜텍: {result}")

result2 = extract_meaningful_keywords(titles, "삼성전자")
print(f"Result for 삼성전자: {result2}")
