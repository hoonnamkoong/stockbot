import os

def clean_json_file(filepath):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
        
    try:
        # Read with utf-8-sig to automatically handle BOM if present
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            content = f.read().strip()
            
        # Write back as plain utf-8 (no BOM)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
            
        print(f"Successfully cleaned: {filepath}")
    except Exception as e:
        print(f"Error cleaning {filepath}: {e}")

# Target files in the active data directory
files_to_clean = [
    'data/reservations.json',
    'data/order_history.json',
    'data/kis_token_cache.json',
    'data/reports.json'
]

if __name__ == "__main__":
    for f in files_to_clean:
        clean_json_file(f)
