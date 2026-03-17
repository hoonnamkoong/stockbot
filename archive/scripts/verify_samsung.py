import sys
import pandas as pd
from src import analyzer_5days

# Force re-read of reports.json
print("Running 5-Day Analysis...")
df = analyzer_5days.analyze_5days()

if df.empty:
    print("DataFrame is empty!")
    sys.exit(1)

# Find Samsung Electronics (005930)
samsung = df[df['code'] == '005930']

if not samsung.empty:
    print("\n[Samsung Electronics Found]")
    row = samsung.iloc[0]
    print(f"Name: {row['name']}")
    print(f"Consecutive Days: {row['consecutive_days']}")
    print(f"Total Posts: {row['total_posts']}")
    print(f"Sparkline (Price): {row['sparkline_price']}")
else:
    print("\n[Samsung Electronics NOT FOUND in 5-day analysis]")
    print(f"Top 5 rows:\n{df.head(5)[['code', 'name', 'consecutive_days']]}")
