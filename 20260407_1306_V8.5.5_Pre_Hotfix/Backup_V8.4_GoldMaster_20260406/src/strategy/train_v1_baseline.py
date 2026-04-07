import os
import sys
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.strategy.hybrid_advisor_sandbox import HybridAnalyzerSandbox

def train_initial_model():
    data_path = r"C:\Users\Hoon_DT\gemini\stock\scraping data\combined_scraping_data.csv"
    model_dir = r"C:\Users\Hoon_DT\gemini\stock\src\strategy\models"
    model_name = "v2026-01-02--2026-02-28.joblib"
    model_path = os.path.join(model_dir, model_name)
    
    if not os.path.exists(model_dir):
        os.makedirs(model_dir)
        
    print(f"[*] Starting training for version: {model_name}")
    print(f"[*] Source data: {data_path}")
    
    sandbox = HybridAnalyzerSandbox(data_path=data_path, version="v2026-01-02--2026-02-28")
    
    success = sandbox.train_ml_model()
    if success:
        sandbox.save_model(model_path)
        print(f"[+] Successfully saved model to {model_path}")
    else:
        print("[-] Training failed. Check data availability.")

if __name__ == "__main__":
    train_initial_model()
