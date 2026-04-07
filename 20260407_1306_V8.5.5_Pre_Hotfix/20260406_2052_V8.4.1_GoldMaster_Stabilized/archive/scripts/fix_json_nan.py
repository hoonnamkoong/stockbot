import json
import pandas as pd
import numpy as np
import math
import os

def sanitize_for_json(obj):
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    if pd.isna(obj):
        return None
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
    return obj

target_files = ['data/latest_stocks.json', 'data/all_stocks.json']

for file_path in target_files:
    if os.path.exists(file_path):
        print(f"Sanitizing {file_path}...")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # Load as raw string first to avoid json.load error if it's invalid?
                # No, standard json.load might accept specific NaN if allowed, but we want to load it and CLEAN it.
                # If json.load fails due to NaN, we might need a more aggressive approach.
                # But Python json.load handles NaN by default.
                data = json.load(f)
            
            clean_data = sanitize_for_json(data)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(clean_data, f, ensure_ascii=False, indent=4)
            print(f"✅ Saved clean {file_path}")
        except Exception as e:
            print(f"❌ Error processing {file_path}: {e}")
