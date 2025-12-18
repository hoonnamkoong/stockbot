
import holidays
from datetime import datetime, timedelta

def check_holiday():
    # Simulate scraper.py logic
    now_utc = datetime.utcnow()
    now_kst = now_utc + timedelta(hours=9)
    # Force today to be 2025-12-15 checking
    # now_kst = datetime(2025, 12, 15, 15, 0, 0) # Debug fixed date
    
    print(f"Current KST: {now_kst}")
    
    kr_holidays = holidays.KR()
    is_weekend = now_kst.weekday() >= 5
    is_holiday = now_kst.strftime('%Y-%m-%d') in kr_holidays
    
    print(f"Is Weekend? {is_weekend}")
    print(f"Is Holiday? {is_holiday}")
    
    if is_holiday:
        print(f"Holiday Name: {kr_holidays.get(now_kst.strftime('%Y-%m-%d'))}")

if __name__ == "__main__":
    check_holiday()
