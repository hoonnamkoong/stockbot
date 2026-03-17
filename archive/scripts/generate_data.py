
import os
import sys
import pandas as pd

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src import analyzer_5days

def generate_data():
    print("Generating 3-Day Analysis Data...")
    df_3days = analyzer_5days.analyze_3days()
    if not df_3days.empty:
        output_path = 'data/analysis_3days.json'
        df_3days.to_json(output_path, orient='records', force_ascii=False)
        print(f"Saved {len(df_3days)} records to {output_path}")
    else:
        print("No data generated for 3 days.")

    print("\nGenerating 5-Day Analysis Data (Refresh)...")
    df_5days = analyzer_5days.analyze_5days()
    if not df_5days.empty:
        output_path = 'data/analysis_5days.json'
        df_5days.to_json(output_path, orient='records', force_ascii=False)
        print(f"Saved {len(df_5days)} records to {output_path}")
    else:
        print("No data generated for 5 days.")

if __name__ == "__main__":
    generate_data()
