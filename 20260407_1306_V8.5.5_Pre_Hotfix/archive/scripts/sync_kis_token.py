import os
import json
import requests
import base64
from trade.auth import get_access_token
from datetime import datetime, timedelta

# GitHub Info
REPO_OWNER = 'hoonnamkoong'
REPO_NAME = 'stockbot'
BRANCH = 'db-data'
TOKEN_PATH = 'data/kis_token.json'
# Load env manually
def load_env(env_path=".env.local"):
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'): continue
                if '=' in line:
                    k, v = line.split('=', 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")

load_env()
GITHUB_PAT = os.environ.get("GITHUB_PAT")

def update_github_token():
    print("[Sync] Getting fresh token from KIS...")
    token = get_access_token()
    if not token:
        print("[Error] Failed to get KIS token locally.")
        return

    # KIS Token expires in 24h, let's set it
    expires_at = (datetime.now() + timedelta(hours=23)).isoformat()
    token_data = {
        "access_token": token,
        "expires_at": expires_at
    }

    if not GITHUB_PAT:
        print("[Error] GITHUB_PAT not found in env.")
        return

    headers = {
        'Authorization': f'Bearer {GITHUB_PAT}',
        'Accept': 'application/vnd.github.v3+json'
    }

    # 1. Get current SHA
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{TOKEN_PATH}?ref={BRANCH}"
    res = requests.get(url, headers=headers)
    sha = ""
    if res.status_code == 200:
        sha = res.json().get('sha', '')
        print(f"[Sync] Found existing token. SHA: {sha}")
    else:
        print("[Sync] No existing token on GitHub. Creating new one.")

    # 2. Update File
    content = base64.b64encode(json.dumps(token_data, indent=2).encode('utf-8')).decode('utf-8')
    payload = {
        "message": "Update KIS token via sync script",
        "content": content,
        "branch": BRANCH
    }
    if sha:
        payload["sha"] = sha

    put_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{TOKEN_PATH}"
    put_res = requests.put(put_url, headers=headers, json=payload)

    if put_res.status_code in [200, 201]:
        print("[Sync] Successfully updated KIS token on GitHub branch db-data.")
    else:
        print(f"[Sync] Failed to update: {put_res.status_code} - {put_res.text}")

if __name__ == "__main__":
    update_github_token()
