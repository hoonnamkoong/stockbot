import requests
from bs4 import BeautifulSoup
import re
import pandas as pd

def verify_naver_stock(code):
    print(f"\n--- Verifying Stock: {code} ---")
    url = f"https://finance.naver.com/item/frgn.naver?code={code}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.content, 'html.parser')
        
        # 1. 외인/기관 매매동향 테이블
        rows = soup.select('table.type2 tr')
        print(f"Total rows found in table.type2: {len(rows)}")
        
        data_rows = []
        for r in rows:
            cols = r.select('td')
            if len(cols) == 9:
                date_text = cols[0].get_text(strip=True)
                if re.match(r'\d{4}\.\d{2}\.\d{2}', date_text):
                    data_rows.append(cols)
        
        print(f"Data rows found: {len(data_rows)}")
        
        if len(data_rows) >= 2:
            # col indices: 0:Date, 1:Close, 2:Diff, 3:Rate, 4:Vol, 5:Inst, 6:ForeigNet, 7:ForeigHold, 8:ForeigRate
            today = data_rows[0]
            yesterday = data_rows[1]
            
            t_close = today[1].get_text(strip=True).replace(',','')
            t_foreign_net = today[6].get_text(strip=True).replace(',','')
            t_foreign_rate = today[8].get_text(strip=True).replace('%','')
            
            y_foreign_rate = yesterday[8].get_text(strip=True).replace('%','')
            
            print(f"Today ({today[0].get_text(strip=True)}):")
            print(f"  Close: {t_close}")
            print(f"  Foreign Net Buy: {t_foreign_net}")
            print(f"  Foreign Rate: {t_foreign_rate}%")
            print(f"Yesterday ({yesterday[0].get_text(strip=True)}):")
            print(f"  Foreign Rate: {y_foreign_rate}%")
            
            change = round(float(t_foreign_rate) - float(y_foreign_rate), 3)
            print(f"Calculated Foreign Change: {change}%")
        else:
            print("Not enough data rows found.")
            
        # 2. 전일 종가 확인 (메인 페이지 등에서)
        # scraper.py 에서는 어떻게 가져오는지 확인 필요. 
        # 현재 scraper.py에서는 get_stock_details 내부에서 prev_close를 가져오는 로직이 안 보임.
        # analyzer.py 에서 전달해 주거나 다른 방식으로 가져오고 있을 것.
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    verify_naver_stock("005930") # 삼성전자
    verify_naver_stock("003280") # 흥아해운
