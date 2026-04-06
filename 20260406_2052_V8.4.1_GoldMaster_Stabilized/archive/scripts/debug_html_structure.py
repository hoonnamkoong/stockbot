
import requests
from bs4 import BeautifulSoup

def inspect_html():
    url = "https://finance.naver.com/sise/sise_quant.naver"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    print(f"Fetching {url}...")
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.content.decode('euc-kr', 'replace'), 'html.parser')
        
        # Find ANY table
        tables = soup.find_all('table')
        print(f"Found {len(tables)} tables.")
        
        for i, table in enumerate(tables):
            classes = table.get('class', [])
            print(f"Table {i} classes: {classes}")
            # Check if this table has stock data (look for a known stock like Samsung 005930)
            if "005930" in str(table):
                print(f"  -> MATCH! This table contains Samsung Electronics.")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_html()
