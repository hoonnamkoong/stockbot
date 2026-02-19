
import requests
from bs4 import BeautifulSoup
import urllib.parse

def fetch_news_from_search(query):
    # sort=1 (Date), query={query}
    encoded_query = urllib.parse.quote(query)
    # Mobile URL (m.search.naver.com)
    url = f"https://m.search.naver.com/search.naver?where=m_news&query={encoded_query}&sm=mtb_opt&sort=1&photo=0&field=0&pd=0&ds=&de=&docid=&related=0&mynews=0&office_type=0&office_section_code=0&news_office_checked=&nso=so%3Add%2Cp%3Aall"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36"
    }
    
    print(f"Fetching: {url}")
    res = requests.get(url, headers=headers)
    
    soup = BeautifulSoup(res.text, 'html.parser')
    
    # Print structure to find news items
    print(f"HTML Size: {len(res.text)} chars")
    
    print("\n--- Inspecting .group_news structure ---")
    groups = soup.select('.group_news')
    for i, g in enumerate(groups[:2]):
        print(f"Group {i}:")
        # Print all classes of children
        for child in g.descendants:
            if child.name and child.get('class'):
                print(f"  Tag: {child.name}, Class: {child.get('class')}, Text: {child.get_text()[:30].strip()}...")
                
    # Attempt to extract
    news_list = []
    for g in groups:
        # Try to find the title link. unique class might be 'news_tit' but maybe it is 'tit'
        # Look for <a> tag with some text
        links = g.find_all('a')
        for a in links:
            # Title usually has longest text or specific class
            if len(a.get_text(strip=True)) > 10:
                print(f"  Potential Title: {a.get_text(strip=True)} | Class: {a.get('class')}")
                # Use this if it looks like a title
                # For now, let's assume the first long link is the title
                news_list.append({'title': a.get_text(strip=True), 'link': a['href'], 'source': 'MobileSearch'})
                break # Only one title per group
                
    return news_list

if __name__ == "__main__":
    test_queries = ["삼성전자", "SK하이닉스", "한화솔루션"]
    for q in test_queries:
        print(f"\n--- Results for {q} ---")
        results = fetch_news_from_search(q)
        for r in results:
            print(f"[{r['source']}] {r['title']}")
