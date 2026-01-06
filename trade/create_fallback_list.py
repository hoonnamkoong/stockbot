import json
import os

# Top ~100 stocks (Manual Fallback List)
# Ideally we would scrape this, but for robustness in this environment, a static list of top caps is safer.
stocks = [
    {"code": "005930", "name": "삼성전자"},
    {"code": "000660", "name": "SK하이닉스"},
    {"code": "373220", "name": "LG에너지솔루션"},
    {"code": "207940", "name": "삼성바이오로직스"},
    {"code": "005380", "name": "현대차"},
    {"code": "000270", "name": "기아"},
    {"code": "068270", "name": "셀트리온"},
    {"code": "005490", "name": "POSCO홀딩스"},
    {"code": "035420", "name": "NAVER"},
    {"code": "006400", "name": "삼성SDI"},
    {"code": "051910", "name": "LG화학"},
    {"code": "035720", "name": "카카오"},
    {"code": "003670", "name": "포스코퓨처엠"},
    {"code": "028260", "name": "삼성물산"},
    {"code": "105560", "name": "KB금융"},
    {"code": "012330", "name": "현대모비스"},
    {"code": "055550", "name": "신한지주"},
    {"code": "000810", "name": "삼성화재"},
    {"code": "032830", "name": "삼성생명"},
    {"code": "042700", "name": "한미반도체"},
    {"code": "015760", "name": "한국전력"},
    {"code": "018260", "name": "삼성에스디에스"},
    {"code": "323410", "name": "카카오뱅크"},
    {"code": "086520", "name": "에코프로"},
    {"code": "247540", "name": "에코프로비엠"},
    {"code": "022100", "name": "포스코DX"},
    {"code": "091990", "name": "셀트리온헬스케어"},
    {"code": "066970", "name": "엘앤에프"},
    {"code": "025980", "name": "아난티"},
    {"code": "035900", "name": "JYP Ent."},
    {"code": "122870", "name": "와이지엔터테인먼트"},
    {"code": "352820", "name": "하이브"},
    {"code": "003550", "name": "LG"},
    {"code": "034020", "name": "두산에너빌리티"},
    {"code": "034220", "name": "LG디스플레이"},
    {"code": "010130", "name": "고려아연"},
    {"code": "096770", "name": "SK이노베이션"},
    {"code": "011200", "name": "HMM"},
    {"code": "010950", "name": "S-Oil"},
    {"code": "009150", "name": "삼성전기"},
    {"code": "003490", "name": "대한항공"},
    {"code": "030200", "name": "KT"},
    {"code": "017670", "name": "SK텔레콤"},
    {"code": "090430", "name": "아모레퍼시픽"},
    {"code": "009540", "name": "HD한국조선해양"},
    {"code": "005935", "name": "삼성전자우"},
    # Add more key stocks if needed
]

output_path = os.path.join('..', 'data', 'all_stocks.json')
# Ensure directory exists
os.makedirs(os.path.dirname(output_path), exist_ok=True)

with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(stocks, f, ensure_ascii=False, indent=2)

print(f"Manually created {output_path} with {len(stocks)} major stocks.")
