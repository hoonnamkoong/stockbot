import requests
import os

def send_telegram_message(message, bot_token=None, chat_id=None):
    """
    Sends a message to Telegram.
    Prioritizes arguments, then Environment Variables.
    """
    token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat:
        print("[Telegram] Missing Token or Chat ID.")
        return False
    
    # Debug: Check token format (Masked)
    print(f"[Telegram] Token Length: {len(token)}")
    print(f"[Telegram] Token Starts with: {token[:4]}***")
    print(f"[Telegram] Chat ID: {chat}")
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat,
        "text": message,
        "parse_mode": "HTML" # Use HTML for bolding keys
    }
    
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print("[Telegram] Message sent.")
            return True
        else:
            print(f"[Telegram] Failed: {res.text}")
            return False
            
    except Exception as e:
        print(f"[Telegram] Error: {e}")
        return False
