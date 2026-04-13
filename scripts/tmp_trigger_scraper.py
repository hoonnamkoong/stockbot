import requests
import os

def trigger_scraper():
    owner = "hoonnamkoong"
    repo = "stockbot"
    token = "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"
    event_type = "tasker_trigger"
    
    url = f"https://api.github.com/repos/{owner}/{repo}/dispatches"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {token}",
        "Content-Type": "application/json"
    }
    data = {
        "event_type": event_type
    }
    
    print(f"Triggering repository_dispatch to {url}...")
    try:
        res = requests.post(url, headers=headers, json=data)
        if res.status_code == 204:
            print("OK Success! GitHub Action triggered.")
        else:
            print(f"FAILED Status: {res.status_code}")
            print(res.text)
    except Exception as e:
        print(f"ERROR: {str(e)}")

if __name__ == "__main__":
    trigger_scraper()
