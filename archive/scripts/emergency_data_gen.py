import json
import os
from datetime import datetime

def generate_emergency_data():
    print("Generating Emergency Data...")
    
    # Hardcoded Backup Data
    stocks = [
        {"code": "005930", "name": "삼성전자", "market": "KOSPI", "price": 74100, "change_rate": "0.54%", "posts_summary": "Emergency Backup Data"},
        {"code": "000660", "name": "SK하이닉스", "market": "KOSPI", "price": 138500, "change_rate": "1.20%", "posts_summary": "Emergency Backup Data"},
        {"code": "035420", "name": "NAVER", "market": "KOSPI", "price": 205000, "change_rate": "-0.45%", "posts_summary": "Emergency Backup Data"},
        {"code": "035720", "name": "카카오", "market": "KOSPI", "price": 54300, "change_rate": "0.10%", "posts_summary": "Emergency Backup Data"},
        {"code": "005380", "name": "현대차", "market": "KOSPI", "price": 245000, "change_rate": "2.50%", "posts_summary": "Emergency Backup Data"},
        {"code": "247540", "name": "에코프로비엠", "market": "KOSDAQ", "price": 230000, "change_rate": "-1.50%", "posts_summary": "Emergency Backup Data"},
        {"code": "086520", "name": "에코프로", "market": "KOSDAQ", "price": 510000, "change_rate": "-1.00%", "posts_summary": "Emergency Backup Data"},
        {"code": "293490", "name": "카카오게임즈", "market": "KOSDAQ", "price": 24500, "change_rate": "0.80%", "posts_summary": "Emergency Backup Data"},
    ]
    
    # Fill required fields
    for s in stocks:
        s.update({
             "prev_close": 0,
             "foreign_rate": "0.00%",
             "recent_posts_count": 0,
             "sentiment": "Neutral",
             "top_keywords": "Backup",
             "is_last_captured": False
        })

    os.makedirs('data', exist_ok=True)
    
    # Save to BOTH files
    with open('data/latest_stocks.json', 'w', encoding='utf-8') as f:
        json.dump(stocks, f, ensure_ascii=False, indent=4)
    
    with open('data/all_stocks.json', 'w', encoding='utf-8') as f:
        json.dump(stocks, f, ensure_ascii=False, indent=4)
        
    # Save Status
    status_data = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "ok",
        "message": "Emergency Backup"
    }
    with open('data/status.json', 'w', encoding='utf-8') as f:
        json.dump(status_data, f, ensure_ascii=False, indent=4)
        
    print("Emergency data saved.")

if __name__ == "__main__":
    generate_emergency_data()
