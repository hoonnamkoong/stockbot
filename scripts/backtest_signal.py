"""신호 백테스트 하네스 — 일봉으로 '진입 신호 → 익일 매매' 규칙을 잰다.

왜 만드는가: 임계값을 바꿀 때마다 일회성 스크립트를 짰고, 그게 검증이 계속
미뤄진 이유였다. 2026-08-15에 심1의 A안(ignition4 게이트 연결)을 그럴듯하게
설계했다가 재보니 승률이 48% → 33%로 **떨어져서** 기각했다. 재보기 전에는
알 수 없었다.

## 룩어헤드를 만들지 않는 규칙

- 신호는 **D일 종가까지의 정보만** 쓴다(거래대금 급증 배수 = D일 거래대금 /
  직전 20일 평균). D일 종가 시점에 실제로 알 수 있는 값이다.
- 매수는 **D+1 시가**. 신호를 본 다음 첫 체결 가능 지점이다.
- 지정가 익절은 **D+1 고가가 목표가에 닿았는지**로 판정한다. 이건 룩어헤드가
  아니다 — 장 시작 때 걸어둔 지정가 매도는 고가가 그 가격에 닿으면 체결된다.
- 미체결이면 **D+1 종가**에 청산한다.

일봉이라 장중 트레일링·시각 손절은 못 잰다. 그건 분봉이 필요하고, 지금
분봉 표본은 급등 종목만 저장돼 있어 편향돼 있다(별도 과제).

사용:
    PYTHONPATH=. python scripts/backtest_signal.py --from 20260701 --to 20260731
    PYTHONPATH=. python scripts/backtest_signal.py --min-amul 3 --take 3.0
"""
import argparse
import collections
import csv
import os
import statistics as st

DEFAULT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           '..', 'output', 'ohlcv_top100.csv')
LOOKBACK = 20          # 거래대금 평균 기간
FEE_PCT = 0.18         # 왕복 수수료+세금 근사(%). 실제 체결 비용은 fees.py가 정확하다.


def load(path):
    by = collections.defaultdict(list)
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            try:
                for k in ('open', 'high', 'low', 'close', 'amount'):
                    r[k] = float(r[k] or 0)
            except ValueError:
                continue
            if r['close'] > 0:
                by[r['code']].append(r)
    for c in by:
        by[c].sort(key=lambda x: x['date'])
    return by


def signals(by, min_amul, min_chg, date_from, date_to):
    """(신호일, 종목, 급증배수, 등락률, D+1 봉)."""
    out = []
    for code, s in by.items():
        for i in range(LOOKBACK, len(s) - 1):
            cur, nxt = s[i], s[i + 1]
            if date_from and cur['date'] < date_from:
                continue
            if date_to and cur['date'] > date_to:
                continue
            hist = [x['amount'] for x in s[i - LOOKBACK:i] if x['amount'] > 0]
            if not hist or cur['amount'] <= 0:
                continue
            amul = cur['amount'] / st.mean(hist)
            chg = (cur['close'] / s[i - 1]['close'] - 1) * 100 if s[i - 1]['close'] else 0
            if amul < min_amul or chg < min_chg:
                continue
            if nxt['open'] <= 0:
                continue
            out.append((cur['date'], code, amul, chg, nxt))
    return out


def simulate(sigs, take_pct, fee=FEE_PCT):
    """익일 시가 매수 → 지정가 익절(+take%) → 미체결 시 종가 청산."""
    rows = []
    for date, code, amul, chg, nxt in sigs:
        entry = nxt['open']
        target = entry * (1 + take_pct / 100)
        if nxt['high'] >= target:
            ret, hit = take_pct, True
        else:
            ret, hit = (nxt['close'] / entry - 1) * 100, False
        rows.append(dict(date=date, code=code, amul=amul, chg=chg,
                         ret=ret - fee, hit=hit))
    return rows


def report(label, rows):
    if not rows:
        print(f'{label:26} 신호 0건')
        return
    r = [x['ret'] for x in rows]
    win = 100 * sum(1 for x in r if x > 0) / len(r)
    hit = 100 * sum(1 for x in rows if x['hit']) / len(rows)
    print(f'{label:26} n={len(rows):4} 승률 {win:5.1f}%  평균 {st.mean(r):+6.2f}%  '
          f'중앙 {st.median(r):+6.2f}%  익절체결 {hit:4.1f}%')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', default=DEFAULT_CSV)
    ap.add_argument('--from', dest='date_from', default='')
    ap.add_argument('--to', dest='date_to', default='')
    ap.add_argument('--min-amul', type=float, default=3.0, help='거래대금 급증 배수 하한')
    ap.add_argument('--min-chg', type=float, default=-100.0, help='당일 등락률 하한(%)')
    ap.add_argument('--take', type=float, default=0.0, help='지정가 익절(%). 0이면 종가 청산만')
    args = ap.parse_args()

    by = load(args.csv)
    sigs = signals(by, args.min_amul, args.min_chg, args.date_from, args.date_to)
    period = f'{args.date_from or "전체"}~{args.date_to or ""}'
    print(f'[백테스트] {period} | 급증>={args.min_amul}배, 등락률>={args.min_chg}% '
          f'| 종목 {len(by)}개 → 신호 {len(sigs)}건\n')
    if not sigs:
        return
    report('종가 청산 (익절 없음)', simulate_close(sigs))
    for t in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0):
        report(f'지정가 익절 +{t}%', simulate(sigs, t))


def simulate_close(sigs, fee=FEE_PCT):
    out = []
    for date, code, amul, chg, nxt in sigs:
        entry = nxt['open']
        out.append(dict(date=date, code=code, amul=amul, chg=chg,
                        ret=(nxt['close'] / entry - 1) * 100 - fee, hit=False))
    return out


if __name__ == '__main__':
    main()
