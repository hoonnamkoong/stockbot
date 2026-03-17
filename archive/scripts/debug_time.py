
from datetime import datetime, timedelta
import pytz

def check_time():
    print(f"Local Now: {datetime.now()}")
    print(f"UTC Now: {datetime.utcnow()}")
    
    kst_wrong = datetime.now() + timedelta(hours=9)
    kst_correct = datetime.utcnow() + timedelta(hours=9)
    
    print(f"Now + 9h (Current Logic): {kst_wrong}")
    print(f"UTC + 9h (Proposed Logic): {kst_correct}")

    # Check date strings for today
    print(f"Date String (Current): {kst_wrong.strftime('%Y-%m-%d')}")
    print(f"Date String (Proposed): {kst_correct.strftime('%Y-%m-%d')}")

if __name__ == "__main__":
    check_time()
