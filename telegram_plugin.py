import requests
import os
import json

def send_telegram_message(message):
    """
    Sends a message to the configured Telegram chat.
    Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables.
    """
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')

    if not token or not chat_id:
        print("[Telegram] Skipping notification: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not found.")
        return

    # Telegram limit is 4096 chars. careful split.
    MAX_LENGTH = 4000
    messages = [message[i:i+MAX_LENGTH] for i in range(0, len(message), MAX_LENGTH)]

    for i, msg_chunk in enumerate(messages):
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": msg_chunk,
            "parse_mode": "Markdown" 
        }

        try:
            print(f"[Telegram] Sending chunk {i+1}/{len(messages)}...")
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            print(f"[Telegram] Chunk {i+1} sent successfully (Markdown).")
        except Exception as e:
            print(f"[Telegram] Markdown send failed for chunk {i+1}: {e}. Retrying as Plain Text...")
            try:
                # Remove parse_mode and retry
                del payload['parse_mode']
                response = requests.post(url, json=payload, timeout=10)
                response.raise_for_status()
                print(f"[Telegram] Chunk {i+1} sent successfully (Plain Text).")
            except Exception as e2:
                 print(f"[Telegram] Failed to send chunk {i+1} (Plain Text): {e2}")
                 if 'response' in locals():
                     print(f"[Telegram] Response: {response.text}")

if __name__ == "__main__":
    # Test
    send_telegram_message("🔔 Test Message from Stock Dashboard")
