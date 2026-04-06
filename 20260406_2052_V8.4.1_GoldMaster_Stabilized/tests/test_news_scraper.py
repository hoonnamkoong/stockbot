import requests
from bs4 import BeautifulSoup

def fetch_specific_news(code):
    # Try the standard iframe URL with minimal params
    url = f"https://finance.naver.com/item/news_news.naver?code={code}&page=1"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": f"https://finance.naver.com/item/main.naver?code={code}" 
    }
    
    print(f"Fetching: {url}")
    res = requests.get(url, headers=headers)
    res.encoding = 'EUC-KR'
    
    # Save for debug (overwrite)
    with open('debug_news.html', 'w', encoding='utf-8') as f:
        f.write(res.text)
        
    soup = BeautifulSoup(res.text, 'html.parser')
    
    news_list = []
    
    # Check for 'type5' table
    # Try different selectors
    titles = soup.select('.title')
    if not titles:
        titles = soup.select('.tit')
    if not titles:
         # Try finding all links in a simple way
         links = soup.find_all('a', class_='tit')
         if links: titles = links
         
    print(f"Found {len(titles)} potential titles")
    
    for t in titles[:5]: # Top 5
        # If t is 'td', find 'a'
        if t.name == 'td':
            a_tag = t.find('a')
        else:
            a_tag = t
            
        if a_tag:
            title = a_tag.get_text(strip=True)
            link = "https://finance.naver.com" + a_tag['href']
            
            # Source finding
            source = "Unknown"
            try:
                # Common structure: td.title -> td.info -> td.date
                # If 't' is 'td', parent is 'tr'
                if t.name == 'td':
                    tr = t.find_parent('tr')
                    tds = tr.find_all('td')
                    if len(tds) >= 3:
                        source = tds[1].get_text(strip=True)
                # If 't' is 'a', we need to go up
                elif t.name == 'a':
                     parent = t.find_parent('td')
                     if parent:
                         tr = parent.find_parent('tr')
                         tds = tr.find_all('td')
                         if len(tds) >= 3:
                            source = tds[1].get_text(strip=True)
            except: pass
            
            news_list.append({'title': title, 'link': link, 'source': source})
            
    return news_list

if __name__ == "__main__":
    # Test with Samsung Electronics (005930) and a smaller cap for variety
    print("--- Samsung Elec (005930) ---")
    news1 = fetch_specific_news('005930')
    for n in news1:
        print(f"[{n['source']}] {n['title']}")
        
    print("\n--- SK Hynix (000660) ---")
    news2 = fetch_specific_news('000660')
    for n in news2:
        print(f"[{n['source']}] {n['title']}")
