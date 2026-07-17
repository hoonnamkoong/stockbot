"""07시 토큰 발급 직후 KIS 개장일 달력을 갱신한다.

token_manager.py가 data/kis_token_cache.json에 토큰을 남긴 뒤 실행되어야 한다.
실패는 exit 1이다 — 조용히 넘어가면 스크래퍼가 판정 불가로 정지한다.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.market_calendar import refresh_calendar


def main():
    today = (datetime.utcnow() + timedelta(hours=9)).strftime('%Y%m%d')
    try:
        days = refresh_calendar(today)
    except Exception as e:
        print(f"[MarketCalendar] 갱신 실패: {e}")
        sys.exit(1)

    opnd = days.get(today, '?')
    print(f"[MarketCalendar] {len(days)}일치 저장 완료. "
          f"오늘({today}) 개장여부={opnd}")


if __name__ == '__main__':
    main()
