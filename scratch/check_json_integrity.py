import json
import os

def check_json_integrity(filepath):
    print(f"--- Checking {filepath} ---")
    try:
        with open(filepath, 'rb') as f:
            raw = f.read()
        
        content = raw.decode('utf-8').strip()
        data = json.loads(content)
        
        print(f"[SUCCESS] Valid JSON with {len(data)} entries.")
        if len(data) > 0:
            # We use repr() to avoid encoding issues with Korean stock names in some terminals
            # But the terminal here should handle Korean if we are careful.
            try:
                print(f"Sample First Entry: {data[0].get('title', data[0].get('종목명', 'N/A'))}")
                print(f"Last Entry: {data[-1].get('title', data[-1].get('종목명', 'N/A'))}")
            except:
                print("Sample Entry had encoding issues during printing.")
            
    except Exception as e:
        print(f"[ERROR] {e}")

if __name__ == "__main__":
    paths = ['data/latest_research.json', 'data/research_latest.json', 'data/reports.json']
    for p in paths:
        if os.path.exists(p):
            check_json_integrity(p)
        else:
            print(f"File {p} not found locally.")
