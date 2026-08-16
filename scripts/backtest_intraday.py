"""장중 조건 백테스터 — 시각이 아니라 **상태**로 진입/청산한다.

왜 만드는가: 2026-08-16 세션이 "09:20 진입 / 10:00 청산" 같은 고정 시각을
격자 탐색했고, 국면이 바뀌면 그 값이 옮겨가 매번 무너졌다. 사용자 지적:
**"시점은 언제나 가변하는 거니 의미 없다. 진입 조건과 청산 조건을 찾아라."**

그래서 분 단위로 상태를 훑으며 조건이 충족되는 순간 체결한다. 시각은 입력이
아니라 결과다.

## 룩어헤드를 만들지 않는 규칙

t분의 상태는 **t분까지의 봉만** 쓴다. 전일 정보(급증배수·등락률·지수추세)는
당연히 쓸 수 있다. 체결가는 그 분의 종가(`price`)로 잡는다 — 그 분 안에서
고가/저가를 골라 쓰면 그게 룩어헤드다.

## 데이터

    output/research/daily400.csv      일봉(급증배수·전일종가)
    output/research/sig_minutes_v3.csv 신호 종목 분봉(거래량 포함)
    output/research/etf_minutes.csv   KODEX200/코스닥150 분봉(시장 상태)
    output/research/index_daily.csv   지수 일봉(5일 추세)

사용:
    PYTHONPATH=. python scripts/backtest_intraday.py --help
"""
import argparse
import collections
import csv
import os
import statistics as st

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'output', 'research')
FEE_PCT = 0.18          # 왕복 수수료+세금 근사(%)
KOSPI_ETF = '069500'
KOSDAQ_ETF = '229200'
LAST_CONTINUOUS = '1519'   # 15:20~15:30은 종가 동시호가라 연속 체결이 없다


def _elapsed(a, b):
    """hhmm 두 개 사이의 경과 분. 고정 시각이 아니라 **보유 시간**을 재기 위한 것."""
    return (int(b[:2]) * 60 + int(b[2:])) - (int(a[:2]) * 60 + int(a[2:]))


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def load_minutes(path):
    """(date,code) -> [(hhmm, price, high, low, vol), ...] 시간순."""
    by = collections.defaultdict(list)
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            by[(r['date'], r['code'])].append(
                (r['hhmm'], _f(r['price']), _f(r['high']), _f(r['low']), _f(r.get('vol'))))
    for k in by:
        by[k].sort()
    return by


def load_daily(path):
    by = collections.defaultdict(list)
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if _f(r['close']) > 0:
                by[r['code']].append(dict(date=r['date'], name=r.get('name', ''),
                                          close=_f(r['close']), amount=_f(r['amount'])))
    for c in by:
        by[c].sort(key=lambda x: x['date'])
    return by


def load_index_trend(path, days=5):
    """거래일 -> 직전 `days`일 KOSPI 추세(%). 진입일 시점에 알 수 있는 값만."""
    close = {}
    with open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['index'] == 'KOSPI':
                close[r['date']] = _f(r['close'])
    dts = sorted(close)
    out = {}
    for i, d in enumerate(dts):
        if i >= days + 1:
            out[d] = 100 * (close[dts[i - 1]] / close[dts[i - 1 - days]] - 1)
    return out


def signals(daily, min_amul, min_chg, lookback=20):
    """(신호일, 매매일, code, 급증배수, 등락률). D일 종가까지의 정보만 쓴다."""
    out = []
    for code, s in daily.items():
        for i in range(lookback, len(s) - 1):
            hist = [x['amount'] for x in s[i - lookback:i] if x['amount'] > 0]
            if not hist or s[i]['amount'] <= 0 or s[i - 1]['close'] <= 0:
                continue
            amul = s[i]['amount'] / st.mean(hist)
            chg = (s[i]['close'] / s[i - 1]['close'] - 1) * 100
            if amul >= min_amul and chg >= min_chg:
                out.append((s[i]['date'], s[i + 1]['date'], code, amul, chg,
                            s[i]['close'], s[i]['name']))
    return out


def market_state(etf, date, code):
    """시장 ETF의 분별 상태: hhmm -> (시초대비%, 고점대비되밀림%)."""
    bars = etf.get((date, code)) or []
    if not bars:
        return {}
    open_px = bars[0][1]
    out, peak = {}, open_px
    for hhmm, price, high, low, vol in bars:
        peak = max(peak, price)
        out[hhmm] = (100 * (price / open_px - 1) if open_px else 0,
                     100 * (price / peak - 1) if peak else 0)
    return out


def run(sig, minutes, etf, trend, args):
    """조건이 충족되는 순간 진입, 조건이 충족되는 순간 청산."""
    trades = []
    for sig_date, trade_date, code, amul, chg, prev_close, name in sig:
        bars = minutes.get((trade_date, code))
        if not bars or len(bars) < 300:
            continue
        kospi = market_state(etf, trade_date, KOSPI_ETF)
        kosdaq = market_state(etf, trade_date, KOSDAQ_ETF)
        if args.require_market and not kospi:
            continue
        tr = trend.get(trade_date)
        if tr is None:
            continue
        if not (args.trend_min <= tr <= args.trend_max):
            continue

        open_px = bars[0][1]
        gap = 100 * (open_px / prev_close - 1) if prev_close else 0
        if not (args.gap_min <= gap <= args.gap_max):
            continue

        # 장 초반 거래량 기준선 — 첫 20봉
        base_vol = st.mean([b[4] for b in bars[:20]]) or 1

        entry = None
        peak = open_px
        closed = False
        last_bar = None
        recent = collections.deque(maxlen=5)
        for hhmm, price, high, low, vol in bars:
            if hhmm > LAST_CONTINUOUS:
                continue
            last_bar = (hhmm, price)
            peak = max(peak, price)
            recent.append(vol)
            mkt = kospi.get(hhmm, (0, 0))
            mkt_q = kosdaq.get(hhmm, (0, 0))

            if entry is None:
                if hhmm < args.no_entry_before:
                    continue
                # --- 진입 조건 ---
                vol_ratio = (sum(recent) / len(recent)) / base_vol
                from_open = 100 * (price / open_px - 1)
                ok = (mkt[0] >= args.mkt_min
                      and mkt_q[0] >= args.mktq_min
                      and vol_ratio >= args.vol_ratio_min
                      and args.from_open_min <= from_open <= args.from_open_max)
                if ok:
                    entry = (hhmm, price)
                    peak = price
                continue

            # --- 청산 조건 ---
            e_hhmm, e_px = entry
            ret = 100 * (price / e_px - 1)
            drawdown = 100 * (price / peak - 1)
            vol_ratio = (sum(recent) / len(recent)) / base_vol
            hit = None
            if args.take > 0 and ret >= args.take:
                hit = 'take'
            elif args.stop > 0 and ret <= -args.stop:
                hit = 'stop'
            elif args.trail > 0 and drawdown <= -args.trail:
                hit = 'trail'
            elif args.vol_dry > 0 and vol_ratio <= args.vol_dry:
                hit = 'vol_dry'
            elif args.mkt_break < 0 and mkt[1] <= args.mkt_break:
                hit = 'mkt_break'
            elif args.max_hold > 0 and _elapsed(e_hhmm, hhmm) >= args.max_hold:
                hit = 'max_hold'
            if hit:
                trades.append(dict(date=trade_date, code=code, name=name, entry=e_hhmm,
                                   exit=hhmm, ret=ret - FEE_PCT, why=hit, trend=tr))
                entry, closed = None, True
                break
        # 조건이 끝내 안 걸리면 마지막 연속체결가로 강제 청산(안전장치)
        if entry is not None and not closed and last_bar:
            e_hhmm, e_px = entry
            trades.append(dict(date=trade_date, code=code, name=name, entry=e_hhmm,
                               exit=last_bar[0], ret=100 * (last_bar[1] / e_px - 1) - FEE_PCT,
                               why='forced', trend=tr))
    return trades


def report(trades, label=''):
    if not trades:
        print(f'{label} 거래 0건')
        return
    r = [t['ret'] for t in trades]
    codes = collections.Counter(t['code'] for t in trades)
    top = sorted(r)[:-10] if len(r) > 10 else r
    print(f'{label} n={len(r):4} 평균 {st.mean(r):+6.2f}% 중앙 {st.median(r):+6.2f}% '
          f'승률 {100 * sum(1 for x in r if x > 0) / len(r):3.0f}% '
          f'| 고유 {len(codes)}종목 상위10제외 {st.mean(top):+.2f}%')
    print(f'{"":>{len(label)}} 청산사유 {dict(collections.Counter(t["why"] for t in trades))}')


def main():
    ap = argparse.ArgumentParser(description='장중 조건 백테스터')
    ap.add_argument('--minutes', default=os.path.join(R, 'sig_minutes_v3.csv'))
    ap.add_argument('--daily', default=os.path.join(R, 'daily400.csv'))
    ap.add_argument('--min-amul', type=float, default=2.0, help='전일 거래대금 급증 배수 하한')
    ap.add_argument('--min-chg', type=float, default=7.0, help='전일 등락률 하한(%)')
    # 진입 조건
    ap.add_argument('--mkt-min', type=float, default=-99, help='KOSPI ETF 시초대비 하한(%)')
    ap.add_argument('--mktq-min', type=float, default=-99, help='KOSDAQ ETF 시초대비 하한(%)')
    ap.add_argument('--vol-ratio-min', type=float, default=0.0, help='최근5분 거래량/장초반 평균 하한')
    ap.add_argument('--from-open-min', type=float, default=-99, help='시초 대비 위치 하한(%)')
    ap.add_argument('--from-open-max', type=float, default=99, help='시초 대비 위치 상한(%)')
    ap.add_argument('--gap-min', type=float, default=-99, help='시가 갭 하한(%)')
    ap.add_argument('--gap-max', type=float, default=99, help='시가 갭 상한(%)')
    ap.add_argument('--trend-min', type=float, default=-99, help='직전 5일 지수 추세 하한(%)')
    ap.add_argument('--trend-max', type=float, default=99, help='직전 5일 지수 추세 상한(%)')
    ap.add_argument('--no-entry-before', default='0900', help='이 시각 전에는 진입하지 않는다')
    ap.add_argument('--require-market', action='store_true', help='ETF 분봉 없는 날 제외')
    # 청산 조건
    ap.add_argument('--take', type=float, default=0.0, help='이익 목표(%)')
    ap.add_argument('--stop', type=float, default=0.0, help='손절(%)')
    ap.add_argument('--trail', type=float, default=0.0, help='고점 대비 되밀림(%)')
    ap.add_argument('--vol-dry', type=float, default=0.0, help='거래량 소멸 배수 이하면 청산')
    ap.add_argument('--mkt-break', type=float, default=0.0, help='시장 고점대비 되밀림(%, 음수)')
    ap.add_argument('--max-hold', type=int, default=0, help='보유 상한(분). 시각이 아니라 경과 시간이다')
    ap.add_argument('--by', default='', help="분해 출력: month | trend")
    args = ap.parse_args()

    daily = load_daily(args.daily)
    minutes = load_minutes(args.minutes)
    etf = load_minutes(os.path.join(R, 'etf_minutes.csv'))
    trend = load_index_trend(os.path.join(R, 'index_daily.csv'))
    sig = signals(daily, args.min_amul, args.min_chg)
    print(f'[조건 백테스트] 신호 {len(sig)}건 | 분봉 보유 {len(minutes)}쌍\n')

    trades = run(sig, minutes, etf, trend, args)
    report(trades, '전체')
    if args.by == 'month':
        for m in sorted({t['date'][:6] for t in trades}):
            report([t for t in trades if t['date'].startswith(m)], f'{m}')
    elif args.by == 'trend':
        buckets = (('급락<-5', -99, -5), ('약세-5~0', -5, 0), ('강세0~5', 0, 5), ('급등>5', 5, 99))
        for lbl, lo, hi in buckets:
            report([t for t in trades if lo <= t['trend'] < hi], f'{lbl}')


if __name__ == '__main__':
    main()
