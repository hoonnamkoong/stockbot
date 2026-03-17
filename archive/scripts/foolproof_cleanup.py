import json
import os

def force_clean_utf8(filepath):
    print(f"[Cleanup] Force cleaning {filepath}...")
    # Try reading as UTF-16 first (since we saw interleaving)
    data = None
    try:
        with open(filepath, 'r', encoding='utf-16') as f:
            data = json.load(f)
        print(f"  [Info] Successfully read {filepath} as UTF-16")
    except:
        try:
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
            print(f"  [Info] Successfully read {filepath} as UTF-8 (BOM detected)")
        except:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            print(f"  [Info] Successfully read {filepath} as standard UTF-8")

    if data:
        with open(filepath, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"  [Success] Saved {filepath} as clean UTF-8 (No BOM)")
    else:
        print(f"  [Error] Could not parse {filepath} with any known encoding.")

if __name__ == "__main__":
    files = ['data/gemini_portfolio.json', 'data/kis_token.json', 'data/token.json']
    for f in files:
        if os.path.exists(f):
            force_clean_utf8(f)
