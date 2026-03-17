import json
import os

def fix_encoding(filepath):
    print(f"[Fix] Cleaning encoding for {filepath}...")
    try:
        # Read as binary to handle any BOM or null bytes
        with open(filepath, 'rb') as f:
            content = f.read()
            
        # Strip BOM if present
        if content.startswith(b'\xef\xbb\xbf'):
            content = content[3:]
        elif content.startswith(b'\xff\xfe') or content.startswith(b'\xfe\xff'):
            # It's likely UTF-16, try to decode and re-encode
            print(f"[Warn] {filepath} appears to be UTF-16, converting to UTF-8")
            content = content.decode('utf-16').encode('utf-8')
        else:
            # Try to decode as utf-8 and clean
            text = content.decode('utf-8', errors='ignore')
            # Remove null bytes or weird interleaving
            text = text.replace('\x00', '')
            content = text.encode('utf-8')

        # Load as JSON to verify
        data = json.loads(content)
        
        # Write back as clean UTF-8
        with open(filepath, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[Success] {filepath} is now clean UTF-8.")
    except Exception as e:
        print(f"[Error] Failed to fix {filepath}: {e}")

if __name__ == "__main__":
    fix_encoding('data/gemini_portfolio.json')
    # Also sync local token to kis_token.json if it exists
    if os.path.exists('data/token.json'):
        # Just rewrite it using the same logic
        with open('data/token.json', 'r', encoding='utf-8') as f:
            d = json.load(f)
        with open('data/kis_token.json', 'w', encoding='utf-8', newline='\n') as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
        print("[Success] Synchronized token.json to kis_token.json")
