import requests
from bs4 import BeautifulSoup

HEADER = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def diagnose_company():
    print("=== DIAGNOSING COMPANY LIST PAGE ===")
    url = "https://finance.naver.com/research/company_list.naver"
    
    print(f"Fetching {url}")
    res = requests.get(url, headers=HEADER)
    res.encoding = 'EUC-KR'
    soup = BeautifulSoup(res.text, 'html.parser')
    
    table = soup.find('table', {'class': 'type_1'})
    if not table:
        print("CRITICAL: Table class 'type_1' NOT FOUND.")
        return

    print("Table 'type_1' found.")
    rows = table.find_all('tr')
    
    for i, row in enumerate(rows[:10]): # Check first 10 rows
        cols = row.find_all('td')
        if len(cols) < 2: continue
        
        print(f"\n[Row {i}]")
        # Print all links in this row
        links = row.find_all('a', href=True)
        for a in links:
            print(f"  Link: {a.text.strip()} -> {a['href']}")

if __name__ == "__main__":
    diagnose_company()
