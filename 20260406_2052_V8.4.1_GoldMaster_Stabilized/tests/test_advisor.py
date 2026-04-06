
import sys
import os
import json

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy.advisor import StrategyAdvisor

def test_advisor():
    print("Initializing StrategyAdvisor...")
    advisor = StrategyAdvisor()
    
    # Mock Data
    candidates = [
        {
            'code': '005930', 'name': 'Samsung Elec', 'price': 70000, 'change_rate': '+1.5%',
            'foreign_rate': '50.1%', 'prev_foreign_rate': '50.0%',
            'consecutive_days': 3, 'recent_posts_count': 100, 
            'top_keywords': 'Galaxy, Earnings, HBM'
        },
        {
            'code': '000660', 'name': 'SK Hynix', 'price': 140000, 'change_rate': '-2.0%',
            'foreign_rate': '48.0%', 'prev_foreign_rate': '49.0%', # Sell Signal Trigger
            'consecutive_days': 1, 'recent_posts_count': 80,
            'top_keywords': 'DRAM, Loss'
        }
    ]
    
    print("Running generate_report...")
    report, results = advisor.generate_report(candidates)
    
    print("\n=== Report Output ===")
    print(report)
    
    print("\n=== Detailed Results ===")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    
    # Verification
    print("\n=== Verification ===")
    for item in results:
        news_count = len(item.get('news', []))
        print(f"Stock: {item['name']} - News Count: {news_count}")
        if news_count > 0:
            print(f"  First News: {item['news'][0]['title']} ({item['news'][0]['link']})")
        else:
            print(f"  WARNING: No news found for {item['name']}")

if __name__ == "__main__":
    test_advisor()
