"""마감 후 당일 1분봉 저장 — eod_data.yml에서 하루 한 번.

왜 필요한가: 2026-08-09 재구성의 신호는 60~120초 격자인데 가격은 diag의 10분
격자에만 있다. 4분짜리 신호를 10분 가격으로 재면 향후 수익률의 대부분이 신호와
무관한 구간이라 신호 대 잡음이 구조적으로 나쁘다. **표본을 늘리지 않고 검정력을
올리는 유일한 항목이 가격 해상도다.**

왜 마감 후인가: KIS 분봉(FHKST03010200)은 **당일치만** 조회된다. 과거로 소급할 수
없으므로 그날 안에 저장해 두어야 하고, eod_data.yml이 이미 마감 후에 돈다.

대상 종목은 그날 순위 스냅샷(money_YYYY-MM.csv)에 오른 것들이다. 전 종목을 받으면
KIS 유량을 태우면서 분석에 쓰이지도 않는다 — 신호가 순위 차분에서 나오기 때문이다.
"""

import csv
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src import alerts
from src.data.minute_bars import anchor_times, codes_for_date, merge_bars

COLUMNS = ['date', 'code', 'hhmm', 'price', 'volume']

# KIS 유량은 초당 20건이다. 종목당 13콜 × 수십 종목이라 한 번에 몰아치면
# 유량 제한에 걸리고, 그 실패는 조용히 빈 응답으로 돌아온다.
CALL_GAP_SEC = 0.06


def month_path(now, data_dir='data') -> str:
    return os.path.join(data_dir, f"minute_{now.strftime('%Y-%m')}.csv")


def append_bars(date_str: str, code: str, bars: list[dict], path: str) -> int:
    if not bars:
        return 0
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    is_new = not os.path.exists(path)
    with open(path, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction='ignore')
        if is_new:
            w.writeheader()
        for b in bars:
            w.writerow({'date': date_str, 'code': code,
                        'hhmm': b['hhmm'], 'price': b['price'], 'volume': b['volume']})
    return len(bars)


def main() -> None:
    now = (datetime.now(timezone.utc) + timedelta(hours=9)).replace(tzinfo=None)
    date_str = now.strftime('%Y%m%d')

    money = os.path.join('data', f"money_{now.strftime('%Y-%m')}.csv")
    codes = codes_for_date(money, date_str)
    if not codes:
        # 순위 스냅샷이 아직 없는 날(최초 배포)이거나 휴장일. 조용히 끝낸다 —
        # 여기서 죽으면 EOD 잡의 나머지(심9-1·CSV 배포)까지 같이 못 돈다.
        print(f'[분봉] {date_str} 대상 종목 없음 ({money}) — 생략')
        return

    from src.trade.kis_data_provider import KISDataProvider
    p = KISDataProvider()
    path = month_path(now)
    anchors = anchor_times()
    total, failed = 0, 0
    for code in codes:
        batches = []
        for a in anchors:
            try:
                bars = p.get_minute_bars(code, a)
            except Exception as e:
                bars = []
                print(f'[분봉] {code} {a} 실패: {e}')
            # **빈 응답도 실패로 센다.** KISDataProvider._get은 실패해도 예외 없이
            # {}를 준다(토큰 만료·유량 초과·rt_cd≠0) — 예외만 세면 토큰이 죽은 날
            # 13앵커 × 전 종목이 조용히 비는데 아래 로그는 '조회 실패 0콜'이 된다.
            if not bars:
                failed += 1
            else:
                batches.append(bars)
            time.sleep(CALL_GAP_SEC)
        n = append_bars(date_str, code, merge_bars(*batches), path)
        total += n
    # 결손을 조용히 넘기지 않는다 — 분봉이 비면 신호 검정 자체가 성립하지 않는데
    # 로그가 조용하면 '그날은 신호가 없었다'로 오독된다.
    print(f'[분봉] {len(codes)}종목 / {total}행 저장 → {path}'
          + (f' (빈 응답·실패 {failed}콜)' if failed else ''))

    if total == 0:
        # 로그만으로는 부족하다. 이 잡은 `|| echo`로 감싸여 있어 워크플로가 초록색이고,
        # KIS 분봉은 **당일치만** 조회되므로 다음 날 알아채도 복구할 방법이 없다.
        alerts.send_alert(
            f"<b>분봉 저장 실패</b>\n\n"
            f"{date_str} — 대상 {len(codes)}종목이 전부 빈 응답({failed}콜)입니다.\n"
            f"KIS 토큰 또는 유량을 확인하세요.\n"
            f"⚠️ 분봉은 당일치만 조회됩니다 — 이 하루의 가격 해상도는 복구할 수 없습니다.")


if __name__ == '__main__':
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    main()
