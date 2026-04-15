import os
import requests

def trigger_dispatch():
    owner = "hoonnamkoong"
    repo = "stockbot"
    event_type = "refresh_token"
    
    # Try both common PAT names
    pat = os.environ.get('GITHUB_PAT') or os.environ.get('GH_PAT')
    
    if not pat:
        print("❌ Error: GITHUB_PAT or GH_PAT not found in environment.")
        return

    url = f"https://api.github.com/repos/{owner}/{repo}/dispatches"
    headers = {
        "Authorization": f"token {pat}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {
        "event_type": event_type
    }
    
    try:
        res = requests.post(url, json=payload, headers=headers)
        if res.status_code == 204:
            print("🚀 Successfully triggered GitHub Action Token Refresh.")
        else:
            print(f"❌ Failed to trigger Action. Status: {res.status_code}, Body: {res.text}")
    except Exception as e:
        print(f"❌ Error during API call: {e}")

if __name__ == "__main__":
    trigger_dispatch()
