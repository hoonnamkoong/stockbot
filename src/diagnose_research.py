import requests
from bs4 import BeautifulSoup
import re

HEADER = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def diagnose():
    print("=== 1. DIAGNOSING LIST PAGE (Invest) ===")
    url = "https://finance.naver.com/research/invest_list.naver"
    try:
        res = requests.get(url, headers=HEADER)
        res.encoding = 'EUC-KR'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        table = soup.find('table', {'class': 'type_1'})
        if not table:
            print("CRITICAL: Table class 'type_1' NOT FOUND.")
            return

        print("Table 'type_1' found.")
        rows = table.find_all('tr')
        
        valid_row_link = None
        target_title = None
        
        for i, row in enumerate(rows):
            cols = row.find_all('td')
            if len(cols) < 2: continue
            
            a_tag = row.find('a', href=True)
            if a_tag:
                current_link = a_tag['href']
                if 'nid=' in current_link:
                    valid_row_link = current_link
                    target_title = a_tag.get_text(strip=True)[:5] # Capture first 5 chars
                    print(f"Target Title Fragment: '{target_title}'")
                    break

        if valid_row_link:
            print("\n=== 2. DIAGNOSING DETAIL PAGE ===")
            base_url = "https://finance.naver.com/research/"
            if valid_row_link.startswith('/research/'):
                full_link = "https://finance.naver.com" + valid_row_link
            elif valid_row_link.startswith('/'):
                full_link = "https://finance.naver.com" + valid_row_link
            else:
                full_link = base_url + valid_row_link
                
            print(f"Fetching {full_link}")
            
            res_detail = requests.get(full_link, headers=HEADER)
            res_detail.encoding = 'EUC-KR'
            soup_detail = BeautifulSoup(res_detail.text, 'html.parser')
            
            # METHOD 1: Search for title fragment in body
            print(f"\nSearching for '{target_title}' in body...")
            found_elements = soup_detail.find_all(string=re.compile(target_title))
            
            if found_elements:
                print(f"Found {len(found_elements)} occurrences.")
                for i, el in enumerate(found_elements):
                    parent = el.parent
                    print(f"  [Match {i+1}] Parent: <{parent.name} class='{parent.get('class')}' id='{parent.get('id')}'>")
                    # Go up one more level
                    grandparent = parent.parent
                    if grandparent:
                         print(f"      Grandparent: <{grandparent.name} class='{grandparent.get('class')}' id='{grandparent.get('id')}'>")
            else:
                print("Title fragment NOT FOUND in body. Page might be empty or redirected.")
                print(f"Page Title: {soup_detail.title.string if soup_detail.title else 'No Title'}")
            
            # METHOD 2: Dump all DIV IDs/Classes
            print("\nScanning significant DIVs:")
            divs = soup_detail.find_all('div', class_=True)
            for div in divs[:10]: # Print first 10 divs with class
                print(f"  div class='{div['class']}'")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    diagnose()
