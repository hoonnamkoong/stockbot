import pandas as pd
import json
import os
import requests
import io

def fetch_krx_stocks():
    print("Fetching stock master list from KRX...")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        url = 'http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13'
        
        print(f"Downloading from {url}...")
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        
        df = pd.read_html(io.StringIO(res.text), header=0)[0]
        
        # Rename columns
        df = df.rename(columns={'회사명': 'name', '종목코드': 'code'})
        
        # Format code: convert to string first, then pad
        df['code'] = df['code'].astype(str).str.zfill(6)
        
        # Select columns
        result = df[['code', 'name']].to_dict('records')
        
        # Save
        output_path = os.path.join('..', 'data', 'all_stocks.json')
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            
        print(f"SUCCESS: Saved {len(result)} stocks to {output_path}")
        
    except Exception as e:
        print(f"FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    fetch_krx_stocks()
