"""BaseSimulator의 KRW 전제 2개를 흡수하는 공용 US 부모 클래스.

US 심 6개가 전부 이 클래스를 상속한다(개별 심마다 중복 오버라이드하지 않는다).

1. 수수료·세금 — BUY_FEE_RATE/SELL_FEE_RATE/SELL_TAX_RATE는 src/trade/fees.py의
   한국 위탁수수료·증권거래세다. 미국은 리테일 브로커 대부분이 커미션 프리이고
   SEC 초소액 수수료(주당 몇 센트 미만)는 페이퍼 심의 손익 순수성을 지키려고
   반영하지 않는다 — 0으로 둔다.
2. 가격 절사 — BaseSimulator.log_trade()가 CSV에 가격을 int(price)로 적는다.
   원화는 정수 단위라 문제없지만 달러는 $45.67 같은 소수점이 의미를 갖는다.
   여기서 log_trade를 오버라이드해 소수점 2자리를 보존한다.
"""
from .base_simulator import BaseSimulator, ensure_csv_header, get_kst_now, CSV_HEADER
import csv


# US 심 초기자본의 단일 원천. **통화가 다르다**(USD) — 국내의
# DEFAULT_INITIAL_CASH(원)와 섞으면 안 된다. 이 값도 2026-09-01까지 US 심 3곳에
# 각각 박혀 있었고, 국내에서 같은 형태가 사고를 낸 적이 있어 함께 정리한다.
US_DEFAULT_INITIAL_CASH = 20_000


class USBaseSimulator(BaseSimulator):
    BUY_FEE_RATE = 0.0
    SELL_FEE_RATE = 0.0
    SELL_TAX_RATE = 0.0

    def log_trade(self, action, code, name, quantity, price, reason, roi_pct=None, roi_amount=None):
        timestamp = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
        ensure_csv_header(self.csv_file)
        with open(self.csv_file, 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                timestamp, f"{name}({code})", action,
                f"{price:.2f}", quantity, f"{quantity * price:.2f}", reason,
                '' if roi_pct is None else f"{roi_pct:+.2f}",
                '' if roi_amount is None else f"{roi_amount:.2f}",
            ])
