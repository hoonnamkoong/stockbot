
import requests
from bs4 import BeautifulSoup

sections = [
    "https://finance.naver.com/research/company_list.naver",
    "https://finance.naver.com/research/invest_list.naver",
    "https://finance.naver.com/research/industry_list.naver",
    "https://finance.naver.com/research/economy_list.naver"
]

headers = {
    'User-Agent': 'Mozilla/5.0'
}

for url in sections:
    print(f"\n--- Checking {url} ---")
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.content.decode('euc-kr', 'replace'), 'html.parser')

    rows = soup.select('table tr')
    
    count = 0
    for row in rows:
        if count > 2: break 
        print(f"Row Content: {row.get_text(separator='|', strip=True)}")
        links = row.select('a')
        for a in links:
             print(f" Link: {a.get_text()} -> {a.get('href')}")
        count += 1
        count += 1
