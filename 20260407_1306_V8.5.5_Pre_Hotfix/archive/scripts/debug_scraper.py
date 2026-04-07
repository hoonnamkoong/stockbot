
import requests
from bs4 import BeautifulSoup

def test_frgn_parsing(code):
    url_frgn = f"https://finance.naver.com/item/frgn.naver?code={code}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    print(f"Fetching {url_frgn}...")
    response = requests.get(url_frgn, headers=headers)
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # 모든 테이블 검사
    tables = soup.select('table')
    print(f"Found {len(tables)} tables.")
    
    for i, t in enumerate(tables):
        # 테이블 내 텍스트 확인
        txt = t.get_text()
        if '외국인' in txt and '보유율' in txt:
            print(f"Table {i} contains keywords.")
            rows = t.select('tr')
            print(f"Table {i} Row Count: {len(rows)}")
            
            # 첫 5행 출력
            for j, row in enumerate(rows[:5]):
                cols = row.select('td, th')
                vals = [c.get_text(strip=True) for c in cols]
                print(f"Row {j}: {vals}")
            
            # 데이터 행 확인 (날짜 형식이 있는 행 찾기 등)
            # 여기서는 단순히 3번째 행 이후 데이터 출력해봄
            if len(rows) > 3:
                cols_data = rows[3].select('td')
                vals = [c.get_text(strip=True) for c in cols_data]
                print(f"Sample Data Row: {vals}")
                if len(vals) > 0:
                     print(f"Last Col Value: {vals[-1]}")


    else:
        print("Table not found.")

if __name__ == "__main__":
    # Test with Samsung Electronics (005930) and one from the list
    test_frgn_parsing("005930")
