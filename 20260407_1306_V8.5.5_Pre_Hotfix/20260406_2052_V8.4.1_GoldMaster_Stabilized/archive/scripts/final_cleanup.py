import json
import os

def write_clean_json(filepath, data):
    print(f"[Cleanup] Writing {filepath} as clean UTF-8...")
    # Write as bin to be absolutely sure about BOM
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    with open(filepath, 'w', encoding='utf-8', newline='\n') as f:
        f.write(json_str)
    print(f"[Success] {filepath} written.")

if __name__ == "__main__":
    # 1. Clean Portfolio
    portfolio_data = {
      "cash": 3000000,
      "holdings": {},
      "trade_log": [],
      "last_update": "2026-03-17"
    }
    write_clean_json('data/gemini_portfolio.json', portfolio_data)
    
    # 2. Sync Fresh Token
    if os.path.exists('data/token.json'):
        with open('data/token.json', 'r', encoding='utf-8') as f:
            token_data = json.load(f)
        write_clean_json('data/kis_token.json', token_data)
