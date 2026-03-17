
import os
import telegram_plugin

def load_env_manual(filepath=".env.local"):
    print(f"Loading env from {filepath}...")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    os.environ[key] = value
                    print(f"Loaded {key}")
    except Exception as e:
        print(f"Error loading {filepath}: {e}")

if __name__ == "__main__":
    load_env_manual()
    print("Testing Telegram...")
    try:
        telegram_plugin.send_telegram_message("🔔 Debug Test Message: If you see this, Telegram is working.")
    except Exception as e:
        print(f"Telegram failed: {e}")
