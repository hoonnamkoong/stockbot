import json
import os
import datetime
from datetime import timedelta, timezone

def kst_convert(iso_str):
    try:
        # ISO 형식 (+00:00 or Z) 확인
        if isinstance(iso_str, str) and ('Z' in iso_str or '+00:00' in iso_str or 'T' in iso_str):
            # T만 포함되고 Z/+00:00이 없는 경우 (로컬 ISO)는 이미 KST일 가능성이 높음
            if 'T' in iso_str and not ('Z' in iso_str or '+00:00' in iso_str):
                return iso_str
            
            clean_str = iso_str.replace('Z', '+00:00')
            dt = datetime.datetime.fromisoformat(clean_str)
            kst_dt = dt.astimezone(timezone(timedelta(hours=9)))
            return kst_dt.strftime('%Y-%m-%d %H:%M:%S')
        return iso_str
    except:
        return iso_str

def process_file(filepath):
    if not os.path.exists(filepath):
        return

    with open(filepath, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except:
            return

    modified = False
    
    def walk(obj):
        nonlocal modified
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ['timestamp', 'executed_at', 'last_update', 'created_at', 'time', 'entry_date']:
                    if isinstance(v, str):
                        new_v = kst_convert(v)
                        if v != new_v:
                            obj[k] = new_v
                            modified = True
                else:
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)

    if modified:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Fixed: {filepath}")
    else:
        print(f"No changes: {filepath}")

def main():
    base_dir = r"c:\Users\Hoon_DT\gemini\stock\data"
    for root, dirs, files in os.walk(base_dir):
        for f in files:
            if f.endswith(".json"):
                process_file(os.path.join(root, f))

if __name__ == "__main__":
    main()
