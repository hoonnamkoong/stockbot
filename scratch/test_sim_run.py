
import os
import sys
import json

# 경로 설정
_REPO_ROOT = os.path.abspath(os.path.join(os.getcwd()))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.strategy.simulators.get_all_stats import run_all_simulators

# 가짜 데이터 생성
mock_data = [
    {"code": "005930", "name": "삼성전자", "price": 75000, "change_rate": "+5.0%", "volume": 20000000, "recent_posts_count": 1000, "avg_posts": 100, "top_keywords": "반도체, AI"},
    {"code": "003280", "name": "흥아해운", "price": 3200, "change_rate": "+2.0%", "volume": 5000000, "recent_posts_count": 500, "avg_posts": 50, "top_keywords": "해운, 물류"},
    {"code": "093370", "name": "후성", "price": 14000, "change_rate": "+1.5%", "volume": 1000000, "recent_posts_count": 100, "avg_posts": 20, "top_keywords": "이차전지, 소재"}
]

print("Running all simulators...")
results = run_all_simulators(mock_data)
print("Results:", json.dumps(results, indent=2, ensure_ascii=False))
