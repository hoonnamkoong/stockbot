import os
import requests
import sys

def test_telegram():
    print("--- Telegram Notification Test ---")
    
    # 1. Ask for credentials (or read from env)
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token:
        token = input("Enter Telegram Bot Token: ").strip()
    if not chat_id:
        chat_id = input("Enter Chat ID: ").strip()
        
    print(f"\nTesting with:")
    print(f"Token: {token[:4]}...{token[-4:] if len(token) > 4 else ''}")
    print(f"Chat ID: {chat_id}")
    
    # 2. Send Message
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "🔔 [StockBot] Test Message: If you see this, notifications are working!",
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        result = response.json()
        
        if response.status_code == 200 and result.get('ok'):
            print("\n✅ SUCCESS: Message sent successfully!")
        else:
            print(f"\n❌ FAILED: {result.get('description', 'Unknown Error')}")
            print(f"Response Code: {response.status_code}")
            
    except Exception as e:
        print(f"\n❌ ERROR: {e}")

if __name__ == "__main__":
    test_telegram()
