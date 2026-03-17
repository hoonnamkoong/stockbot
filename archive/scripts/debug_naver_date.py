
import requests
from bs4 import BeautifulSoup
import datetime

def debug_naver_date():
    code = "005930" # Samsung Electronics
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    url = f"https://finance.naver.com/item/board.naver?code={code}&page=1"
    
    print(f"Fetching {url}...")
    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        table = soup.select_one('table.type2')
        if not table:
            print("Table not found!")
            return

        rows = table.select('tr')
        print(f"Found {len(rows)} rows.")
        
        count = 0
        for row in rows:
            cols = row.select('td')
            if len(cols) < 5:
                continue
            
            date_text = cols[0].get_text(strip=True)
            print(f"Row {count}: DateText='{date_text}'")
            count += 1
            if count >= 10: break
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_naver_date()
