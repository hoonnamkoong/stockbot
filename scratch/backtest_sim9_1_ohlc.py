"""심9-1 재검증 — 진짜 고가/저가·진짜 ATR·거래대금 조건.

현재 구현은 종가 채널 + 근사 ATR이다(네이버 range_history의 한계).
KIS 일봉(FHKST03010100)이 들어오면 원 터틀대로 고가/저가 채널과 True Range ATR을
쓸 수 있고, 지금까지 데이터가 없어 못 걸었던 '거래대금 횡단면 z > 0'도 걸린다.
어느 쪽이 실제로 나은지 같은 기간·같은 유니버스에서 비교한다.

입력: output/ohlcv_top100.csv  (eod_data.yml이 16:00 KST에 생성 → db-data 배포)
      없으면 아래 중 하나로 받는다:
        git show db-data:data/ohlcv_top100.csv > output/ohlcv_top100.csv
        또는 GitHub Actions에서 eod_data 워크플로를 수동 실행
"""
import csv
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.strategy.simulators.sim9_1_donchian import (
    CHANNEL_DAYS, EXIT_DAYS, ATR_STOP_MULT, MAX_HOLDINGS, POSITION_WEIGHT,
    MIN_SAMPLE, MIN_AMOUNT, _atr, _zmap)

PATH = os.path.join(os.path.dirname(__file__), '..', 'output', 'ohlcv_top100.csv')
INITIAL_CASH = 3_000_000
BUY_FEE, SELL_FEE = 0.00015, 0.00015 + 0.0018

if not os.path.exists(PATH):
    sys.exit(f"[중단] {PATH} 없음. eod_data 워크플로가 만든 뒤 다시 실행할 것.\n"
             f"        git show db-data:data/ohlcv_top100.csv > output/ohlcv_top100.csv")

bars = defaultdict(dict)          # code -> {date: bar}
names, dates_set = {}, set()
with open(PATH, encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        try:
            bar = {k: float(r[k]) for k in ('open', 'high', 'low', 'close', 'volume', 'amount')}
        except (ValueError, KeyError, TypeError):
            continue
        if bar['close'] <= 0:
            continue
        bars[r['code']][r['date']] = bar
        names[r['code']] = r.get('name', r['code'])
        dates_set.add(r['date'])

dates = sorted(dates_set)
codes = sorted(bars)
print(f"데이터: {len(dates)}거래일 × {len(codes)}종목 ({dates[0]} ~ {dates[-1]})")


def series(code, t, n):
    """t일 '직전' n일 봉. 결측이 있으면 None."""
    if t < n:
        return None
    out = [bars[code].get(d) for d in dates[t - n:t]]
    return None if any(b is None for b in out) else out


def true_atr(hs):
    """True Range 평균. 갭을 반영하므로 근사 ATR보다 크다 → 손절이 덜 타이트해진다."""
    trs = []
    for i in range(1, len(hs)):
        pc = hs[i - 1]['close']
        trs.append(max(hs[i]['high'] - hs[i]['low'],
                       abs(hs[i]['high'] - pc), abs(hs[i]['low'] - pc)))
    return sum(trs) / len(trs) if trs else 0.0


def run(mode, use_amount):
    """mode: 'close'(현재 구현) | 'ohlc'(원 터틀)"""
    cash, holdings, trades = INITIAL_CASH, {}, []
    for t in range(CHANNEL_DAYS, len(dates)):
        d = dates[t]

        # 청산
        for code, (qty, epx, et) in list(holdings.items()):
            bar = bars[code].get(d)
            hs = series(code, t, CHANNEL_DAYS)
            if not bar or not hs:
                continue
            px = bar['close']
            atr = true_atr(hs) if mode == 'ohlc' else _atr([b['close'] for b in hs])
            reason = None
            if px <= epx - ATR_STOP_MULT * atr:
                reason = 'ATR손절'
            else:
                h10 = series(code, t, EXIT_DAYS)
                if h10:
                    lo = min(b['low'] for b in h10) if mode == 'ohlc' else min(b['close'] for b in h10)
                    if px < lo:
                        reason = '채널이탈'
            if reason:
                proceeds, cost = qty * px * (1 - SELL_FEE), qty * epx * (1 + BUY_FEE)
                cash += proceeds
                trades.append(((proceeds / cost - 1) * 100, reason, t - et, code, d))
                del holdings[code]

        # 거래대금 횡단면 z (심 코드와 동일하게 fail-closed)
        zamt = {}
        if use_amount:
            today_amt = [(c, bars[c][d]['amount']) for c in codes if d in bars[c]]
            if len(today_amt) >= MIN_SAMPLE:
                zamt = _zmap(today_amt)

        # 진입
        nav = cash + sum(q * bars[c].get(d, {'close': e})['close'] for c, (q, e, _) in holdings.items())
        target = nav * POSITION_WEIGHT
        for code in codes:
            if len(holdings) >= MAX_HOLDINGS:
                break
            bar = bars[code].get(d)
            hs = series(code, t, CHANNEL_DAYS)
            if code in holdings or not bar or not hs:
                continue
            if bar['amount'] < MIN_AMOUNT:
                continue
            if use_amount and zamt.get(code, -1) <= 0:
                continue
            ch_hi = max(b['high'] for b in hs) if mode == 'ohlc' else max(b['close'] for b in hs)
            px = bar['close']
            if px <= ch_hi:
                continue
            qty = int(target / px)
            cost = qty * px * (1 + BUY_FEE)
            if qty <= 0 or cost > cash:
                continue
            cash -= cost
            holdings[code] = (qty, px, t)

    final = cash + sum(q * bars[c][dates[-1]]['close'] for c, (q, _, _) in holdings.items()
                       if dates[-1] in bars[c])
    rets = [x[0] for x in trades]
    return trades, rets, final


print(f"\n{'변형':<34}{'거래':>5}{'평균%':>9}{'승률%':>8}{'NAV%':>9}{'상위1제외':>10}")
print('-' * 75)
for label, mode, amt in [("A 종가 채널 + 근사ATR (현재 구현)", 'close', False),
                         ("B 고가/저가 채널 + True ATR", 'ohlc', False),
                         ("C = B + 거래대금 z>0", 'ohlc', True),
                         ("D = A + 거래대금 z>0", 'close', True)]:
    tr, rets, final = run(mode, amt)
    if not rets:
        print(f"{label:<34}{0:>5}{'-':>9}{'-':>8}{(final/INITIAL_CASH-1)*100:>+8.1f}%{'-':>10}")
        continue
    srt = sorted(rets, reverse=True)
    ex1 = sum(srt[1:]) / len(srt[1:]) if len(srt) > 1 else float('nan')
    print(f"{label:<34}{len(rets):>5}{sum(rets)/len(rets):>+8.2f}%"
          f"{sum(1 for x in rets if x > 0)/len(rets)*100:>7.1f}%"
          f"{(final/INITIAL_CASH-1)*100:>+8.2f}%{ex1:>+9.2f}%")

base = [bars[c][dates[-1]]['close'] / bars[c][dates[CHANNEL_DAYS]]['close'] - 1
        for c in codes if dates[-1] in bars[c] and dates[CHANNEL_DAYS] in bars[c]]
print('-' * 75)
print(f"{'기저(동일가중 매수후보유)':<34}{'':>5}{'':>9}{'':>8}{sum(base)/len(base)*100:>+8.2f}%")
