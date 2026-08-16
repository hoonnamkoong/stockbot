"""미국 지수·대표주 일별 수익률을 적재한다. 키 불필요(Yahoo Finance).

왜 지수만 받고 기사는 안 읽는가 (2026-08-16 실측, 20,882 종목-일):

    미국 밤 → 한국 **갭** 상관        SOX +0.367 / 나스닥 +0.393
    미국 밤 → 한국 **시가→종가** 상관   SOX +0.052 / 나스닥 +0.104

**지수 하나가 그 밤의 미국 뉴스를 이미 요약한다.** CNN·Yahoo 기사를 LLM으로
읽어 그보다 나은 걸 뽑아낼 여지가 크지 않다. 지수 4개는 공짜고 정확하다.

그리고 미국 정보로 매매하지는 못한다 — SOX가 +3% 뛴 날 한국 갭은 +1.70%인데
시가→종가는 −0.10%다. 정보의 값이 09:00 시가에 이미 들어가 있다.
**그래서 이 데이터의 용도는 진입 신호가 아니라 국면 판정이다** — 한국 개장 전에
확정된다는 것이 유일한 장점이다.

⚠ 미검증: 종목 특이적 연결(엔비디아 실적 → 한미반도체)은 지수로 안 잡힌다.

사용:
    python scripts/fetch_us_market.py -o data/us_daily.csv --days 120
"""
import argparse
import csv
import datetime as dt
import os
import sys

import requests

SYMBOLS = [
    ('^IXIC', '나스닥'),
    ('^SOX', '필라델피아반도체'),
    ('^GSPC', 'S&P500'),
    ('NVDA', '엔비디아'),
]
HEADERS = {'User-Agent': 'Mozilla/5.0'}


def fetch(symbol, days):
    end = dt.datetime.now()
    start = end - dt.timedelta(days=days)
    r = requests.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}',
                     params={'period1': int(start.timestamp()),
                             'period2': int(end.timestamp()), 'interval': '1d'},
                     headers=HEADERS, timeout=15)
    r.raise_for_status()
    res = r.json()['chart']['result'][0]
    q = res['indicators']['quote'][0]
    out = {}
    for ts, close in zip(res['timestamp'], q['close']):
        if close is None:
            continue
        day = dt.datetime.utcfromtimestamp(ts).strftime('%Y%m%d')
        out[day] = float(close)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', '--out', default='data/us_daily.csv')
    ap.add_argument('--days', type=int, default=120)
    a = ap.parse_args()

    closes, failed = {}, []
    for sym, label in SYMBOLS:
        try:
            closes[sym] = fetch(sym, a.days)
            print(f'  {label:16} {sym:7} {len(closes[sym])}일')
        except Exception as e:
            # 실패를 0으로 바꾸지 않는다. 빠진 심볼은 컬럼이 빈 값으로 남는다.
            failed.append(sym)
            print(f'  {label:16} {sym:7} 실패: {type(e).__name__}', file=sys.stderr)
    if not closes:
        print('전부 실패 — 저장하지 않는다', file=sys.stderr)
        return 1

    # 기존 파일과 병합(이어받기). 같은 날짜는 새 값으로 덮는다.
    rows = {}
    if os.path.exists(a.out):
        with open(a.out, encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                rows[r['date']] = r

    for sym in closes:
        days = sorted(closes[sym])
        for i, d in enumerate(days):
            if i == 0:
                continue
            prev = closes[sym][days[i - 1]]
            if prev <= 0:
                continue
            rows.setdefault(d, {'date': d})[sym] = f'{100 * (closes[sym][d] / prev - 1):.4f}'

    fields = ['date'] + [s for s, _ in SYMBOLS]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for d in sorted(rows):
            w.writerow({k: rows[d].get(k, '') for k in fields})
    print(f'저장 {a.out} ({len(rows)}일){" | 실패 " + ",".join(failed) if failed else ""}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
