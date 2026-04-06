import sys
import os

print("--- [Path Test] ---")
print("CWD:", os.getcwd())
print("sys.path:", sys.path)

try:
    import trade
    print("trade module found:", trade.__file__)
except ImportError as e:
    print("trade module NOT found:", e)

try:
    import src.trade
    print("src.trade module found:", src.trade.__file__)
except ImportError as e:
    print("src.trade module NOT found:", e)

# Add stock root to path if needed (though scraper.py usually does this)
sys.path.append(os.getcwd())
try:
    import trade.auth
    print("trade.auth found:", trade.auth.__file__)
except ImportError as e:
    print("trade.auth NOT found:", e)
