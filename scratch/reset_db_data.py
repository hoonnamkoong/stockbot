import os
import subprocess

def run_git(cmd):
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
    return result.returncode == 0

# 1. Fetch current db-data
run_git("git fetch origin db-data:db-data")

# 2. Extract only reports.json (if exists) or create empty
os.makedirs("data", exist_ok=True)
with open("data/reports.json", "w", encoding="utf-8") as f:
    f.write("[]")

# 3. Commit and Push specifically to db-data branch
run_git("git add data/reports.json")
run_git('git commit -m "data: Reset corrupted report index (v8.9.9.32 cleanup)"')
run_git("git push origin HEAD:db-data")

print("Cleanup script finished.")
