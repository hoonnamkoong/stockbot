
import re

# STOPWORDS from scraper.py v8.2
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

def check_word(word, stock_name):
    print(f"Checking word: '{word}' (Length: {len(word)})")
    
    # 1. Basic Filters
    if len(word) <= 1: return "FAIL: Length <= 1"
    if word.isdigit(): return "FAIL: Is Digit"
    
    # 2. Stopwords
    if word in STOPWORDS: return "FAIL: Exact Match in STOPWORDS"
    if word.lower() in STOPWORDS: return "FAIL: Lowercase Match in STOPWORDS"
    
    # 3. Stock Name
    if stock_name in word: return f"FAIL: Contains Stock Name '{stock_name}'"
    
    # 4. Verb Endings
    if word.endswith(('다', '요', '까', '죠', '임', '함')): return "FAIL: Verb Ending"
    
    # 5. Repetitive
    if len(set(word)) == 1: return "FAIL: Repetitive Chars"
    
    return "PASS: Valid Keyword"

# Test Cases based on user complaint
test_words = ['오늘', '공시', '뉴스', '삼성전자', '오늘도', '이거', '이제']
stock_name = "삼성전자"

# Print ASCII-safe output to stdout
print(f"--- Testing against Stock: {stock_name} ---")
for w in test_words:
    result = check_word(w, stock_name)
    # Print hex of word to confirm identity
    w_hex = "-".join(['%04x' % ord(c) for c in w])
    print(f"Word({w_hex}) -> {result}")

print(f"\nUnicode Check: '오늘' In STOPWORDS? {'오늘' in STOPWORDS}")
