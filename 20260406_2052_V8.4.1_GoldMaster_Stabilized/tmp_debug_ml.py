import os
import sys
import json
import pandas as pd

# Add paths
sys.path.append(os.path.abspath(os.curdir))
sys.path.append(os.path.abspath(os.path.join(os.curdir, 'src')))

from src.strategy.hybrid_advisor_sandbox import HybridAnalyzerSandbox

def test_ml_signal():
    latest_file = 'data/latest_stocks.json'
    archive_file = 'scraping data/combined_scraping_data.csv'
    model_path = 'src/strategy/models/v2026-01-02--2026-02-28.joblib'

    if not os.path.exists(latest_file):
        print(f"Error: {latest_file} not found")
        return

    with open(latest_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print(f"Loaded {len(data)} candidates.")
    sandbox = HybridAnalyzerSandbox(data_path=archive_file, model_path=model_path)
    
    if not sandbox.ml_model:
        print("Error: ML Model failed to load.")
        return

    probs = sandbox.predict_all(data)
    print(f"\n--- Top 10 ML Predictions ---")
    for i, p in enumerate(probs[:10]):
        print(f"#{i+1} {p['name']} ({p['code']}): Prob {p['ml_prob']:.2f}% | Price: {p['price']}")

if __name__ == "__main__":
    test_ml_signal()
