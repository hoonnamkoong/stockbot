
import holidays
from datetime import datetime, timedelta

def check_holiday():
    now_utc = datetime.utcnow()
    now_kst = now_utc + timedelta(hours=9)
    print(f"Current KST: {now_kst}")
    
    kr_holidays = holidays.KR()
    today_str = now_kst.strftime('%Y-%m-%d')
    
    is_weekend = now_kst.weekday() >= 5
    is_holiday = today_str in kr_holidays
    
    print(f"Is Weekend: {is_weekend} (Weekday: {now_kst.weekday()})")
    print(f"Is Holiday: {is_holiday}")
    
    if is_holiday:
        print(f"Holiday Name: {kr_holidays.get(today_str)}")

if __name__ == "__main__":
    check_holiday()
