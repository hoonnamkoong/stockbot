import os
import sys

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

try:
    from strategy.engine import StrategyEngine
    from strategy.advisor import StrategyAdvisor

    print("--- 1. Testing StrategyEngine (Pure Logic) ---")
    engine = StrategyEngine()
    test_stock = {'change_rate': '5.5%', 'foreign_rate': '1.2%'}
    score, p_change = engine.calculate_score(test_stock)
    signal, conf = engine.get_signal(score, p_change)
    print(f"Stock: {test_stock}")
    print(f"Result: Score={score}, Signal={signal}, Confidence={conf}")

    print("\n--- 2. Testing StrategyAdvisor (Coordinator) ---")
    # We won't actually call fetch_portfolio to avoid API hits, 
    # but we verify the object can be instantiated without immediate API calls (lazy loading).
    advisor = StrategyAdvisor()
    print("Advisor instantiated successfully (Lazy Portfolio Loading)")
    
    # Mocking portfolio for a dry run
    advisor._cached_portfolio = {
        '005930': {'name': 'Samsung', 'qty': 10, 'current_price': 70000, 'profit_rate': 12.0}
    }
    
    candidates = [
        {'code': '000660', 'name': 'SK Hynix', 'price': 180000, 'change_rate': '3.0%', 'foreign_rate': '0.5%'}
    ]
    
    results = advisor.analyze_candidates(candidates)
    print(f"Analyzed {len(results)} items (including portfolio stocks).")
    for r in results:
        print(f" - {r['name']}: {r['action']} (Signal: {r['signal']}, Score: {r['score']})")

    print("\n[SUCCESS] Decoupling verified.")

except Exception as e:
    print(f"\n[FAILURE] Verification failed: {e}")
    import traceback
    traceback.print_exc()
