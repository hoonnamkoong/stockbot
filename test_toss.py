import requests
from bs4 import BeautifulSoup
import json

def test_toss():
    url = "https://www.tossinvest.com/feed/news"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        print(f"Status: {response.status_code}")
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Check for Next.js data
        next_data = soup.find('script', {'id': '__NEXT_DATA__'})
        if next_data:
            print("Found __NEXT_DATA__!")
            data = json.loads(next_data.string)
            # print keys to see if we have feed data
            print(data.keys())
            if 'pageProps' in data['props']:
                props = data['props']['pageProps']
                print("PageProps Keys:", props.keys())
                # Try to find something that looks like a list of news
                # Common names: dehydrateState, queries, initialData, feed...
                if 'dehydratedState' in props:
                    print("Found dehydratedState. Checking queries...")
                    queries = props['dehydratedState']['queries']
                    for q in queries:
                        print("Query Key:", q['queryKey'])
                        if 'state' in q and 'data' in q['state']:
                             # Print first item of data to check structure
                             print("Data Sample:", str(q['state']['data'])[:200])
                else:
                    print("No dehydratedState. Dumping props keys...")
                    for k, v in props.items():
                         print(f"{k}: {str(v)[:100]}")
        else:
            print("No __NEXT_DATA__ found.")
            print(response.text[:500])
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_toss()
