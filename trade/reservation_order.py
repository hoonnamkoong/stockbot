import time
from datetime import datetime
import sys
import os
import json
from order import place_order

# from price import get_current_price

# Simple logging
def log(msg):
    with open("reservation_debug.log", "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now()}] {msg}\n")

def update_history(code):
    try:
        # Assuming run from 'trade' dir
        path = os.path.join('..', 'data', 'order_history.json')
        if not os.path.exists(os.path.dirname(path)):
            return # Should exist
            
        history = {}
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except:
                pass
        
        # Format: 2025-01-05 13:35:00
        now_str = datetime.now().strftime("%Y. %m. %d. %H:%M:%S")
        history[code] = now_str
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        log(f"History updated for {code}")
    except Exception as e:
        log(f"Failed to update history: {e}")

def wait_until(target_hour, target_minute):
    now = datetime.now()
    target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
    
    log(f"Started. Target: {target}, Now: {now}")

    if now > target:
        log("Target time has passed. Exiting.")
        print(f"[Reservation] Target time {target.strftime('%H:%M')} has passed.")
        return False
        
    print(f"[Reservation] Waiting until {target.strftime('%H:%M')}...")
    log(f"Waiting for {target}...")
    
    while datetime.now() < target:
        time.sleep(1) 
        
    return True

import random

def schedule_order(code, qty, price, hour, minute, side="buy"):
    log(f"New Schedule: {side.upper()} {code} x {qty} @ {price}, Time: {hour}:{minute}")
    
    ready = wait_until(hour, minute)
    
    if ready:
        # Prevent Rate Limit by adding random jitter (0.5 ~ 5.0 sec)
        jitter = random.uniform(0.5, 5.0)
        log(f"Target reached. Waiting {jitter:.2f}s jitter to distribute load...")
        time.sleep(jitter)
        
        log(f"Triggering Order for {code}...")
        try:
            place_order(side=side, code=code, qty=qty, price=price)
            log("Order function called.")
            if side == "buy":
                update_history(code)
        except Exception as e:
            log(f"Order failed: {e}")
    else:
        log("Skipped order (Time passed).")

if __name__ == "__main__":
    # Usage: python reservation_order.py 005930 1 0 09 00 buy
    try:
        log("Process started.")
        target_code = "005930"
        target_qty = 1
        target_price = 0
        t_hour = 9
        t_min = 0
        t_side = "buy"
        
        if len(sys.argv) > 5:
            target_code = sys.argv[1]
            target_qty = int(sys.argv[2])
            target_price = int(sys.argv[3])
            t_hour = int(sys.argv[4])
            t_min = int(sys.argv[5])
        
        if len(sys.argv) > 6:
            t_side = sys.argv[6]
            
        schedule_order(target_code, target_qty, target_price, t_hour, t_min, t_side)
    except Exception as e:
        log(f"Critical Crash: {e}")
