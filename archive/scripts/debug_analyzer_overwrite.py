
import pandas as pd
from analyzer import analyze_sentiment

# Mock data simulating what scraper.py produces
mock_data = [{
    'name': 'Samsung',
    'all_posts_titles': ['오늘 삼성전자 대박', '공시 떴다', '뉴스 속보', '가즈아'],
    'all_posts_titles': ['오늘 삼성전자 대박', '공시 떴다', '뉴스 속보', '가즈아'],
    'top_keywords': '삼성전자, 대박, 가즈아', # GOOD keywords from scraper (lowercase key)
    # 'top_keywords': '...' # Analyzer might overwrite this if logic is wrong
}]

df = pd.DataFrame(mock_data)

print("Before Analyzer:")
print(df[['name', 'top_keywords']])

# Run analyzer function
df_analyzed = analyze_sentiment(df)

print("\nAfter Analyzer:")
if 'top_keywords' in df_analyzed.columns:
    print(df_analyzed[['name', 'top_keywords']])
else:
    print("top_keywords column missing")
