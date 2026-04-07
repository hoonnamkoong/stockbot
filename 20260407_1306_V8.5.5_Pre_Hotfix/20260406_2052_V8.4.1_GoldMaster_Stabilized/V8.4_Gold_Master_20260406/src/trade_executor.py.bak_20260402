import json
import os
import sys
import time
from datetime import datetime, timezone

# Add 'trade' directory to path to import order.py
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'trade')))

try:
    from order import place_order
except ImportError:
    print("[Error] Could not import 'place_order' from 'trade/order.py'")
    sys.exit(1)

RESERVATIONS_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'reservations.json')

def load_reservations():
    if not os.path.exists(RESERVATIONS_FILE):
        return []
    try:
        with open(RESERVATIONS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[Error] Failed to load reservations: {e}")
        return []

def save_reservations(reservations):
    try:
        with open(RESERVATIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(reservations, f, indent=2, ensure_ascii=False)
        print(f"[System] Updated reservations.json. Count: {len(reservations)}")
    except Exception as e:
        print(f"[Error] Failed to save reservations: {e}")

def main():
    print(f"[Trade Executor] Starting at {datetime.now(timezone.utc)} UTC")
    
    reservations = load_reservations()
    if not reservations:
        print("[Trade Executor] No reservations found.")
        sys.exit(0)

    pending_reservations = []
    executed_count = 0
    now_utc = datetime.now(timezone.utc)

    for res in reservations:
        try:
            # Parse Target Time (Assume ISO Format from JSON)
            # Example: "2025-01-14T04:37:00.000Z"
            target_time_str = res.get('targetTime')
            if not target_time_str:
                pending_reservations.append(res)
                continue

            # Handle Z suffix manually if python version < 3.11 for safety
            if target_time_str.endswith('Z'):
                target_time_str = target_time_str[:-1] + '+00:00'
            
            target_time = datetime.fromisoformat(target_time_str)
            
            # Ensure target_time is timezone-aware (UTC)
            if target_time.tzinfo is None:
                target_time = target_time.replace(tzinfo=timezone.utc)

            # Check Status
            status = res.get('status', 'pending')
            
            # Execution Logic
            if status != 'executed' and now_utc >= target_time:
                print(f"[Trade Executor] Executing Reservation: {res['code']} at {target_time} (Now: {now_utc})")
                
                # Execute Order
                # side, code, qty, price
                place_order(
                    side=res.get('side', 'buy'), 
                    code=res.get('code'), 
                    qty=int(res.get('qty', 1)), 
                    price=int(res.get('price', 0))
                )
                
                # Mark as Executed (OR Remove? User seems to want history?)
                # If we keep it, we must change status.
                # If we remove it, it disappears from list.
                # User's list shows "Active Reservations".
                # Executed orders should move to "Portfolio" or "History".
                # For now, REMOVING from "Active" list is the standard behavior for this app.
                print(f"[Trade Executor] Execution Success. Removing from list.")
                executed_count += 1
                
                # Do NOT append to pending_reservations (effectively deleting it)
                
                # Optional: Add to order_history.json? 
                # (Skipping for now to minimal change, `trade/order.py` might print logs but doesn't auto-save history unless `reservation_order.py` logic used.
                #  But `order.py` prints output. That's fine.)
                
            else:
                # Keep in list
                pending_reservations.append(res)

        except Exception as e:
            print(f"[Error] Failed to process reservation {res.get('id')}: {e}")
            pending_reservations.append(res) # Keep failed ones to retry? Or remove? Keep safety.

    if executed_count > 0:
        save_reservations(pending_reservations)
    else:
        print("[Trade Executor] No reservations triggered.")

if __name__ == "__main__":
    main()
