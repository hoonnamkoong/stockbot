
import subprocess
import datetime

def check_gap():
    try:
        # Fetch latest db-data
        subprocess.run(['git', 'fetch', 'origin', 'db-data'], check=True, capture_output=True)
        
        # List files
        output = subprocess.check_output(['git', 'ls-tree', '-r', 'origin/db-data', '--name-only'], text=True)
        files = output.splitlines()
        
        # Filter for trending_integrated
        data_files = [f for f in files if 'trending_integrated_2026' in f]
        
        existing_dates = set()
        for f in data_files:
            # Extract date: data/trending_integrated_20260115_... or just trending_integrated_...
            parts = f.split('_')
            for part in parts:
                if part.startswith('2026'):
                    existing_dates.add(part[:8])
                    break
        
        # Check gap Jan 16 to Feb 9
        start_date = datetime.date(2026, 1, 16)
        end_date = datetime.date(2026, 2, 9)
        
        missing_dates = []
        current = start_date
        while current <= end_date:
            date_str = current.strftime('%Y%m%d')
            if date_str not in existing_dates:
                missing_dates.append(date_str)
            current += datetime.timedelta(days=1)
            
        print(f"Total files found in db-data (2026): {len(existing_dates)}")
        print(f"Missing dates ({start_date} ~ {end_date}): {len(missing_dates)}")
        if missing_dates:
            print(f"First 5 missing: {missing_dates[:5]}")
            print(f"Last 5 missing: {missing_dates[-5:]}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_gap()
