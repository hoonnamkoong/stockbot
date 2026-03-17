import os
import sys

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from src.strategy.hybrid_advisor_sandbox import HybridAnalyzerSandbox
from src.trade.gemini_trade import GeminiTrader

def test():
    print("Initialize Sandbox...")
    sandbox = HybridAnalyzerSandbox(data_path="scraping data/combined_scraping_data.csv")
    
    print("Training ML model...")
    success = sandbox.train_ml_model()
    print(f"Train success: {success}")
    
    if success:
        import json
        with open('data/latest_stocks.json', 'r', encoding='utf-8') as f:
            all_data = json.load(f)
            
        print(f"Loaded {len(all_data)} stocks from latest_stocks.json")
        all_ml_probs = sandbox.predict_all(all_data)
        print(f"Predicted probs for {len(all_ml_probs)} stocks")
        
        print("Initializing Trader...")
        trader = GeminiTrader()
        
        current_data_map = {
            pick['code']: {
                'price': pick.get('price', 0),
                'ml_prob': pick.get('ml_prob', 50.0)
            } for pick in all_ml_probs
        }
            
        print("Checking Exits...")
        trader.check_exits(current_data_map)
        
        print("Executing Buys...")
        top_ml_picks = sorted(all_ml_probs, key=lambda x: x['ml_prob'], reverse=True)[:5]
        trader.execute_buys(top_ml_picks)
        
        print("Done. State:")
        print(trader.state)

if __name__ == '__main__':
    test()
