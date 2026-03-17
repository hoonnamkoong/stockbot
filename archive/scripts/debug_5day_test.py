import sys
import os

# Add root to path
sys.path.append(os.getcwd())

from src import analyzer_5days
import analyzer # Root directory
import pandas as pd

print("Testing 5-Day Analysis Logic...")
try:
    df = analyzer_5days.analyze_5days()
    print("DataFrame Result:")
    print(df.head())
    
    if not df.empty:
        print("\nTesting Excel Save...")
        analyzer.save_data(pd.DataFrame({'test': [1]}), filename_prefix="test_5day", extra_sheets={'5Day': df})
        print("Excel Saved.")
    else:
        print("Empty DataFrame. Check recent working days logic.")
        
except Exception as e:
    print(f"Error: {e}")
