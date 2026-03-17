
import pandas as pd
import os

# Find a recent excel file
files = [f for f in os.listdir('data') if f.startswith('trending_integrated') and f.endswith('.xlsx')]
if not files:
    print("No trending_integrated xlsx files found.")
else:
    latest_file = sorted(files)[-1]
    path = os.path.join('data', latest_file)
    print(f"Reading columns from {path}...")
    try:
        df = pd.read_excel(path)
        print("Columns:", list(df.columns))
        print("Sample Row:", df.iloc[0].to_dict() if not df.empty else "Empty")
    except Exception as e:
        print(f"Error: {e}")
