
import os

env_path = ".env.local"

def setup_telegram_keys():
    print("Please enter your Telegram credentials.")
    token = input("Telegram Bot Token: ").strip()
    chat_id = input("Telegram Chat ID: ").strip()

    if not token or not chat_id:
        print("Invalid input. Aborted.")
        return

    # Check if file exists to determine if we need newline
    needs_newline = False
    if os.path.exists(env_path):
        with open(env_path, "rb") as f:
            f.seek(-1, 2)
            last_char = f.read(1)
            if last_char != b'\n':
                needs_newline = True

    with open(env_path, "a", encoding="utf-8") as f:
        if needs_newline:
            f.write("\n")
        f.write(f"\nTELEGRAM_BOT_TOKEN={token}\n")
        f.write(f"TELEGRAM_CHAT_ID={chat_id}\n")
    
    print(f"Successfully added credentials to {os.path.abspath(env_path)}")

if __name__ == "__main__":
    setup_telegram_keys()
