import requests
from bs4 import BeautifulSoup
import datetime

def test_links():
    url = "https://finance.naver.com/research/company_list.naver"
    res = requests.get(url)
    soup = BeautifulSoup(res.content.decode('euc-kr', 'replace'), 'html.parser')
    
    print(f"Scanning {url}...")
    
    rows = soup.select('table tr')
    for i, row in enumerate(rows):
        if i > 10: break # Check first 10 rows
        
        links = row.select('a')
        for a in links:
            href = a.get('href', '')
            text = a.get_text(strip=True)
            
            if not href or not text or 'FileDown' in href: continue
            
            # Simulate current logic
            original_href = href
            if 'finance.naver.com' not in href:
                 if href.startswith('/'):
                     href = "https://finance.naver.com" + href
                 elif 'read.naver' in href:
                     href = "https://finance.naver.com/research/" + href
            
            print(f"[{text}]")
            print(f"  Raw: {original_href}")
            print(f"  Final: {href}")
            
            # Check if this is a 'read' link
            if 'read.naver' in href:
                print("  => TARGET LINK")

if __name__ == "__main__":
    test_links()
