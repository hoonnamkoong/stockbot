
import os
import sys

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

try:
    from config_validator import validate_scraper, validate_trade, mask_sensitive
    from notification.notification_service import NotificationService
    
    print("\n--- Test 1: ConfigValidator Masking ---")
    sensitive_token = "ABC123DEF456GHI789JKL012MNO345PQR678STU901"
    print(f"Original: {sensitive_token[:10]}...")
    print(f"Masked:   {mask_sensitive(sensitive_token)}")
    
    print("\n--- Test 2: ConfigValidator Logic (Expected Fail because no env vars) ---")
    # Clean env for test
    for key in ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'KIS_APP_KEY']:
        if key in os.environ: del os.environ[key]
    
    s_ok, s_miss = validate_scraper()
    t_ok, t_miss = validate_trade()
    print(f"Scraper Valid: {s_ok}, Missing: {len(s_miss)}")
    print(f"Trade Valid: {t_ok}, Missing: {len(t_miss)}")

    print("\n--- Test 3: NotificationService Init ---")
    notif = NotificationService()
    print(f"Notification Service Available: {notif.is_available}")

    print("\n--- Test 4: trade_executor logic start ---")
    # We won't run the full main because it sys.exit()s, but we can test import
    import src.trade_executor as te
    print("Trade Executor modules importable.")

    print("\n--- Grand Protocol Verification Complete ---")

except Exception as e:
    print(f"\n❌ Test Failed: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
