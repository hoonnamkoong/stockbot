"""repository_dispatch 수동 발사기 — 태스커 흉내용 점검 도구.

⚠️ 이름과 달리 **스크래퍼를 부르지 않는다.** `tasker_trigger`를 듣는 것은
trading.yml이고(scraper.yml은 `tasker_trigger_scrape`를 듣는다), 스크래퍼는
trade_loop이 10분 격자에서 workflow_dispatch로 깨운다. 즉 이걸 쏘면 실전 매매
워크플로가 돈다.

그리고 실제 태스커는 repository_dispatch를 보내지 않는다(400런 실측 0건,
2026-08-07). 운영 경로를 재현하려면 workflow_dispatch를 써야 한다.
"""
import requests
import os

def trigger_trading():
    owner = "hoonnamkoong"
    repo = "stockbot"
    token = os.environ.get("GITHUB_PAT")
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
    trigger_trading()
