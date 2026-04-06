
import requests
from bs4 import BeautifulSoup
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')


def fetch_post_body_debug(session, link_suffix):
    """
    Test API endpoints
    """
    import json
    
    # Extract NID from suffix
    # suffix: /item/board_read.naver?code=000660&nid=409504331&page=1
    try:
        from urllib.parse import parse_qs, urlparse
        query = parse_qs(urlparse("https://dummy"+link_suffix).query)
        nid = query['nid'][0]
        code = query['code'][0]
        print(f"Extracted NID: {nid}, Code: {code}")
    except:
        print("Failed to extract NID/Code")
        return



def fetch_post_body_debug(session, link_suffix):
    """
    Test Mobile List API
    """
    try:
        from urllib.parse import parse_qs, urlparse
        query = parse_qs(urlparse("https://dummy"+link_suffix).query)
        code = query['code'][0]
        print(f"Extracted Code: {code}")
    except:
        print("Failed to extract Code")
        return

    # Candidates for List API
    urls = [
        f"https://m.stock.naver.com/api/discuss/local/{code}/posts?page=1&pageSize=20",
        f"https://m.stock.naver.com/api/stock/{code}/discuss?page=1",
        f"https://m.stock.naver.com/api/json/discuss/local/{code}/posts?page=1"
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
        'Referer': f"https://m.stock.naver.com/domestic/stock/{code}/discuss",
    }
    
    for url in urls:
        try:
            print(f"Testing List API: {url}")
            res = session.get(url, headers=headers, timeout=5)
            print(f"Status: {res.status_code}")
            with open("debug_api_response.json", "w", encoding="utf-8") as f:
                try:
                    import json
                    json.dump(res.json(), f, ensure_ascii=False, indent=2)
                    print("Saved debug_api_response.json")
                except:
                    f.write(res.text)
                    print("Saved debug_api_response.txt (Not JSON)")
            
            if res.status_code == 200:
                try:
                    data = res.json()
                    print("JSON Success!")
                    print(str(data)[:500]) # Preview
                    return 
                except:
                    print("Not JSON")
        except Exception as e:
            print(f"Error: {e}")
            
    print("All List API tests failed.")

if __name__ == "__main__":
    # Need a valid link suffix. I'll pick a popular stock code and try to find a recent post link first.
    # SK Hynix: 000660
    code = "000660" 
    list_url = f"https://finance.naver.com/item/board.naver?code={code}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    print(f"Fetching board list for {code} to get a test link...")
    session = requests.Session()
    # Visit main board first to set cookies
    res = session.get(list_url, headers=headers)
    soup = BeautifulSoup(res.content, 'html.parser')
    
    # Find first title link
    link_tag = soup.select_one('td.title > a')
    if not link_tag:
        # Retry with different selector just in case
        link_tag = soup.select_one('a.title')
        
    if link_tag:
        suffix = link_tag['href']
        with open("debug_url.txt", "w", encoding="utf-8") as f:
            f.write(f"Suffix: {suffix}\n")
            f.write(f"Full URL: https://finance.naver.com{suffix}\n")
        
        print(f"Found test link: {suffix}")
        fetch_post_body_debug(session, suffix)
    else:
        print("Could not find any post link to test.")
