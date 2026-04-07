
import json
import os

try:
    with open('data/latest_stocks.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    if not data:
        print("Data is empty.")
    else:
        print(f"Data Count: {len(data)}")
        first = data[0]
        # Check specific key 'scraper_version' (might not exist if old)
        ver = first.get('scraper_version', 'MISSING')
        print(f"Scraper Version in Data: {ver}")
        
        print("\n--- Top 5 Keywords ---")
        for i, item in enumerate(data[:5]):
            print(f"[{i+1}] {item['name']} ({item['code']})")
            print(f"    Keywords: {item.get('top_keywords', 'N/A')}")
            print(f"    Consecutive: {item.get('consecutive_days', 'N/A')}")

except Exception as e:
    print(f"Error: {e}")
