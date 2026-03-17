import requests
import json
import time

url = "https://raw.githubusercontent.com/hoonnamkoong/stockbot/main/data/analysis_5days.json?t=" + str(int(time.time()))
print(f"Fetching: {url}")

try:
    resp = requests.get(url)
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        found = False
        for stock in data:
            if stock['code'] == '042660':
                found = True
                print(f"--- REMOTE Hanwha Ocean (042660) ---")
                print(f"Consecutive Days: {stock.get('consecutive_days')}")
                break
        if not found:
            print("Remote: Hanwha Ocean NOT FOUND")
    else:
        print("Failed to fetch")
except Exception as e:
    print(e)
