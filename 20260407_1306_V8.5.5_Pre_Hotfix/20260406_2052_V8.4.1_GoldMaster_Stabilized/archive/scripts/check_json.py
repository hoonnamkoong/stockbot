import json
import os

try:
    file_path = 'data/latest_stocks.json'
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        exit(1)

    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    print(f"Data count: {len(data)}")
    if len(data) > 0:
        first = data[0]
        print(f"First Stock: {first.get('name')}")
        print(f"Keys: {list(first.keys())}")
        
        posts = first.get('latest_posts')
        print(f"Latest Posts Field: {posts is not None}")
        
        if posts:
            print(f"Latest Posts Count: {len(posts)}")
            print(f"First Post Title: {posts[0].get('title')}")
            print(f"First Post Body: '{posts[0].get('body')}'")
        else:
            print("Latest Posts is empty or None.")
            
    else:
        print("No data in JSON.")

except Exception as e:
    print(f"Error: {e}")
