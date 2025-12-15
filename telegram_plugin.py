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
        print(f"[Telegram][SQ_FAIL] Missing Config. Token exists? {bool(token)}, ChatID exists? {bool(chat_id)}")
        return

    # Telegram limit is 4096 chars. careful split.
    MAX_LENGTH = 4000
    messages = [message[i:i+MAX_LENGTH] for i in range(0, len(message), MAX_LENGTH)]

    for i, msg_chunk in enumerate(messages):
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": msg_chunk,
            "parse_mode": "HTML" # Changed to HTML for better stability with simple tags like <b>
        }

        print(f"\n[Telegram][SQ_Probe] Sending Chunk {i+1} (Len: {len(msg_chunk)})")
        print(f"[Telegram][SQ_Payload_Preview] {msg_chunk[:200]}...") 

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            print(f"[Telegram][SQ_Success] Chunk {i+1} sent. Status: {response.status_code}")
        except Exception as e:
            print(f"[Telegram][SQ_Error] HTML send failed: {e}. Retrying as Plain Text...")
            try:
                del payload['parse_mode']
                response = requests.post(url, json=payload, timeout=10)
                response.raise_for_status()
                print(f"[Telegram][SQ_Success] Chunk {i+1} sent (Plain Text).")
            except Exception as e2:
                 print(f"[Telegram][SQ_CRITICAL] Failed to send chunk {i+1}: {e2}")
                 if 'response' in locals():
                     print(f"[Telegram][SQ_Response_Body] {response.text}")

if __name__ == "__main__":
    # Test
    send_telegram_message("🔔 Test Message from Stock Dashboard")
