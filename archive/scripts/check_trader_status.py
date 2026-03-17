import json
import os
from datetime import datetime

PORTFOLIO_PATH = 'data/gemini_portfolio.json'

def check_status():
    print("="*50)
    print("      STOCKBOT - GEMINI TRADER STATUS")
    print("="*50)
    
    if not os.path.exists(PORTFOLIO_PATH):
        print(f"Error: Portfolio file not found at {PORTFOLIO_PATH}")
        return

    with open(PORTFOLIO_PATH, 'r', encoding='utf-8') as f:
        state = json.load(f)

    print(f"Last Update: {state.get('last_update', 'Unknown')}")
    print(f"Algo Ver:    {state.get('algo_version', 'Unknown')}")
    print(f"Market:      {state.get('market_regime', 'Unknown')}")
    print("-" * 50)
    print(f"Current Cash: {state.get('cash', 0):,.0f} KRW")
    
    holdings = state.get('holdings', {})
    if not holdings:
        print("Holdings:     EMPTY")
    else:
        print(f"Holdings:     ({len(holdings)} stocks)")
        print(f"{'Name':<15} {'Qty':<5} {'Avg Price':<12} {'Days':<5}")
        print("-" * 40)
        for code, h in holdings.items():
            name = h.get('name', code)
            qty = h.get('qty', 0)
            avg = h.get('avg_price', 0)
            days = h.get('days_held', 0)
            print(f"{name:<15} {qty:<5} {avg:<12,.0f} {days:<5}")

    print("-" * 50)
    trade_log = state.get('trade_log', [])
    if trade_log:
        last_trade = trade_log[-1]
        print(f"Last Action:  {last_trade['type']} {last_trade.get('name')} on {last_trade['date']}")
    else:
        print("Last Action:  None recorded.")
    print("="*50)

if __name__ == "__main__":
    check_status()
