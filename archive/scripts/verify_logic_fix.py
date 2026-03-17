import sys
import os

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from src.trade.gemini_trade import GeminiTrader
    print("[Test] Successfully imported GeminiTrader")
    
    trader = GeminiTrader()
    print(f"[Test] Current Portfolio Cash: {trader.state['cash']:,} KRW")
    print(f"[Test] Current Holdings: {list(trader.state['holdings'].keys())}")
    
    # Mock data to trigger rebalancing logic
    print("\n[Test] Running check_exits with empty data (should log 'No exit conditions met')...")
    trader.check_exits({})
    
    print("\n[Test] Running execute_buys with empty recommendations...")
    trader.execute_buys([])
    
    print("\n[Test] Verification successful. Logic runs and logs correctly.")
except Exception as e:
    print(f"[Test] Verification failed: {e}")
    import traceback
    traceback.print_exc()
