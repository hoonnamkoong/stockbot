import json
import os
from datetime import datetime

csv_filename = "trending_integrated_20260209_225705.csv"

reports_file = 'data/reports.json'
try:
    with open(reports_file, 'r', encoding='utf-8') as f:
        reports = json.load(f)
except:
    reports = []

# Mock entry
new_entry = {
    "type": "daily",
    "date": datetime.now().strftime('%Y-%m-%d %H:%M'),
    "filename": csv_filename,
    "count": 100, # Dummy
    "timestamp": datetime.now().timestamp()
}

# Insert at top
reports.insert(0, new_entry)

with open(reports_file, 'w', encoding='utf-8') as f:
    json.dump(reports, f, ensure_ascii=False, indent=2)

print(f"Updated reports.json with {csv_filename}")
