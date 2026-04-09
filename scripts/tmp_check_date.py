import requests
from bs4 import BeautifulSoup
import re

def check_naver_date_format():
    code = '005930'
    url = f"https://finance.naver.com/item/board.naver?code={code}"
    res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(res.content, 'html.parser')
    rows = soup.select('table.type2 tr')
    for row in rows:
        cols = row.select('td')
        if len(cols) >= 5:
            date_text = cols[0].get_text(strip=True)
            title = row.select_one('td.title a').get_text(strip=True)
            print(f"Date: {date_text} | Title: {title}")

if __name__ == "__main__":
    check_naver_date_format()
