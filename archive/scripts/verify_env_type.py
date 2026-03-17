from trade.auth import load_env
import os

load_env()
base_url = os.environ.get("KIS_BASE_URL", "")

print(f"Base URL: {base_url}")
if "vts" in base_url or "29443" in base_url:
    print("Environment: PAPER TRADING (Virtual)")
else:
    print("Environment: REAL TRADING")
    
# Also check if keys exist
print(f"App Key Present: {bool(os.environ.get('KIS_APP_KEY'))}")
print(f"App Secret Present: {bool(os.environ.get('KIS_APP_SECRET'))}")
