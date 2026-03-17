
import os
import time
import telegram_plugin

# Mock Env for local testing (User provided DASHBOARD_URL previously, checking if it works)
# We rely on load_env_manual in real script, but here we manually set or check.
print("[SQ_TEST] Starting Dashboard Link Test...")

# 1. Simulate the exact logic from scraper.py
dashboard_url = os.environ.get('DASHBOARD_URL', 'https://stockbot-phi.vercel.app/')

print(f"[SQ_TEST] Resolved Dashboard URL: {dashboard_url}")

if dashboard_url:
    try:
        msg = f"📊 <b>Dashboard Check (SQ Test)</b>\n{dashboard_url}"
        print(f"[SQ_TEST] Attempting to send: {msg}")
        telegram_plugin.send_telegram_message(msg)
        print("[SQ_TEST] Send function returned.")
    except Exception as e:
        print(f"[SQ_TEST] Exception during send: {e}")
else:
    print("[SQ_TEST] No Dashboard URL found (Logic Failure).")
