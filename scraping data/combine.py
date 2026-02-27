import pandas as pd
import glob
import os
import re

# Set folder path
folder_path = r'C:\Users\Hoon_DT\gemini\stock\scraping data'

# 1. Load monthly reports
monthly_files = glob.glob(os.path.join(folder_path, 'monthly_report_*.xlsx'))
dfs = []

print(f"Loading {len(monthly_files)} monthly files...")
for file in monthly_files:
    try:
        df = pd.read_excel(file)
        dfs.append(df)
    except Exception as e:
        print(f"Error loading {file}: {e}")

# 2. Load daily files
daily_csv = glob.glob(os.path.join(folder_path, 'trending_integrated_*.csv'))
daily_xlsx = glob.glob(os.path.join(folder_path, 'trending_integrated_*.xlsx'))

# To avoid duplicates if both csv and xlsx exist, use a dictionary keyed by base timestamp
daily_files_dict = {}
for f in daily_csv + daily_xlsx:
    match = re.search(r'trending_integrated_(\d{8}_\d{6})', f)
    if match:
        timestamp_str = match.group(1)
        # Prefer csv if both exist, so if xlsx is already there and we get csv, overwrite. 
        # Actually dict will just keep the last one, which is fine since they are identical data.
        if timestamp_str not in daily_files_dict or f.endswith('.csv'):
            daily_files_dict[timestamp_str] = f

print(f"Loading {len(daily_files_dict)} daily files...")
for ts_str, file in daily_files_dict.items():
    try:
        if file.endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)
        
        # Add date column if it doesn't exist
        if 'date' not in df.columns:
            # Convert 20251211_122454 to 2025-12-11
            date_str = f"{ts_str[:4]}-{ts_str[4:6]}-{ts_str[6:8]}"
            df['date'] = date_str
            
        dfs.append(df)
    except Exception as e:
        print(f"Error loading {file}: {e}")

# 3. Combine all
if dfs:
    print("Combining datasets...")
    combined_df = pd.concat(dfs, ignore_index=True)
    
    # 4. Drop duplicates (based on code and date and exactly same values if possible)
    # Some daily runs might have the exact same stock multiple times on the same day.
    # Usually we can drop duplicates on ['code', 'date'] keeping the last one.
    if 'code' in combined_df.columns and 'date' in combined_df.columns:
        initial_len = len(combined_df)
        combined_df = combined_df.drop_duplicates(subset=['code', 'date'], keep='last')
        print(f"Dropped {initial_len - len(combined_df)} duplicate rows based on code and date.")
    else:
        # Just drop exact duplicate rows
        combined_df = combined_df.drop_duplicates()
        
    # Save to a single dataset
    output_path = os.path.join(folder_path, 'combined_scraping_data.csv')
    combined_df.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f"Successfully saved combined dataset with {len(combined_df)} rows to {output_path}")
else:
    print("No data found to combine.")
