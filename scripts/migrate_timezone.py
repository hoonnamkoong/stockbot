import requests
import base64
import os

def migrate_csv():
    owner = "hoonnamkoong"
    repo = "stockbot"
    token = "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"
    branch = "db-data"
    files = [
        "data/trade_history_sim_original.csv",
        "data/trade_history_sim_conservative.csv",
        "data/trade_history_sim_aggressive.csv"
    ]
    
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }

    for path in files:
        print(f"Processing {path}...")
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
        res = requests.get(url, headers=headers)
        if res.status_code != 200:
            print(f"  Skip: Not found ({res.status_code})")
            continue
            
        data = res.json()
        sha = data['sha']
        content = base64.b64decode(data['content']).decode('utf-8')
        
        # 2026-04-13 03:xx:xx -> 2026-04-13 12:xx:xx (UTC to KST)
        new_content = content.replace("2026-04-13 03:", "2026-04-13 12:")
        
        if new_content == content:
            print("  No changes needed.")
            continue
            
        # Push back
        payload = {
            "message": f"[V8.9.9.14] Migrate timezone UTC to KST for {path}",
            "content": base64.b64encode(new_content.encode('utf-8')).decode('utf-8'),
            "sha": sha,
            "branch": branch
        }
        update_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        up_res = requests.put(update_url, headers=headers, json=payload)
        
        if up_res.status_code == 200:
            print(f"  ✅ Successfully migrated {path}")
        else:
            print(f"  ❌ Failed to update {path}: {up_res.status_code}")
            print(up_res.text)

if __name__ == "__main__":
    migrate_csv()
