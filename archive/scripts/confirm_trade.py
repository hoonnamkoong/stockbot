import sys
import os

# Add 'trade' directory to path to allow direct imports if package structure is loose
sys.path.append(os.path.join(os.path.dirname(__file__), 'trade'))

from order import place_order
from auth import load_env
import time

# Ensure env is loaded
load_env()

print("--- Starting Virtual Trade Verification ---")
print("Target: Samsung Electronics (005930), Qty: 1, Price: Market (0)")

try:
    # Attempt Market Buy
    # Note: Paper trading market hours might differ or simulation might be 24/7? 
    # Usually KIS Paper Trading works during market hours or specific simulation times.
    # If market is closed, it might queue or fail. 
    # Current time: 15:08 KST -> Market Open (Close at 15:30).
    place_order(side="buy", code="005930", qty=1, price=0)
    print("--- Trade Function Execution Completed ---")
except Exception as e:
    print(f"--- Trade Failed: {e} ---")
