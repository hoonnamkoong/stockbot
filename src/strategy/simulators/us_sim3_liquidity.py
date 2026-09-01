"""US Sim3 — 유동성 상위 보유(기준선 심).

**이 심은 알파를 노리지 않는다. 잣대다.**

2026-08-25에 미국 단타 심 후보 22종을 두 겹으로 검증했다(3개월 5분봉 + 20개월
일봉·시간봉, 2025-01~2026-08 413거래일). 결과는 한 줄이다 — **아무 신호도 쓰지 않고
거래대금 상위를 그냥 들고 있는 쪽이 22종 전부를 이겼다.**

    구성                          누적      MDD     샤프
    거래대금 상위 5 · 20일 리밸런스   +56.0%   -18.5%   +1.20
    거래대금 상위 20 · 20일         +58.9%   -20.0%   +1.19
    ── 검증한 전략들 ──
    RSI(2) 과매도                 +14.6%   -30.4%   +0.38
    3일 낙폭 반전                  +12.9%   -50.4%   +0.43
    52주 신고가 돌파                 -8.9%   -27.2%   -0.09
    ── 지수 매수후보유 ──
    SPY +30.6%(샤프 1.03) / QQQ +38.4%(0.99) / IWM +34.7%(0.96)

지금까지 US 심에는 "이것보다 나은가"를 물을 잣대가 없었다. US Sim1(미너비니)·
US Sim2(돈치안)의 페이퍼 성과가 좋아 보여도, 그게 전략 덕인지 그냥 시장이 올라서인지
가릴 기준이 없었다. 이 심이 그 기준이다.

그래서 **랭킹 외의 어떤 신호도 넣지 않는다.** 과매도든 신고가든 돌파든, 상위 N이면
산다. 필터를 하나라도 얹는 순간 잣대가 아니라 또 하나의 전략이 되고, 비교가 무의미해진다
(tests/test_us_sim3_liquidity.py::test_no_signal_filters_beyond_ranking이 이걸 지킨다).

## 실행 구조

EOD 배치(scripts/run_eod_sim_us.py)가 이미 유니버스 전 종목의 avg_dollar_volume을
계산하고 있다 — US Sim2가 유동성 문턱에 쓰는 값이다. 그걸 그대로 정렬해 상위 N을
워치리스트에 남긴다. **추가 네트워크 호출이 0이다.**

장중 루프(scripts/us_trade_loop.py)는 5분마다 돌지만, 이 심은 20거래일에 한 번만
움직인다. 달력이 아니라 **거래일**을 세야 해서(주말·휴장일이 끼면 달력 날짜는
어긋난다), 워치리스트 날짜가 바뀔 때마다 카운터를 올린다 — 워치리스트는 거래일에만
갱신되므로 이 카운터가 곧 거래일 수다.

## 한계 (이 심을 잣대로 쓸 때 반드시 같이 읽을 것)

- **생존 편향**: 위 백테스트의 유니버스는 "2026-08 시점에 상장돼 있는 보통주"다.
  기간 중 상장폐지·합병된 종목이 통째로 빠졌다. 실제 성과는 저것보다 낮을 것이다.
- **20일 리밸런스는 회차가 20번뿐이었다.** 표본이 작다.
- **거래대금 상위 = 그 시점 가장 뜨거운 종목**이라 사실상 모멘텀 팩터이고,
  2025~2026은 AI 랠리 구간이었다. 국면이 바뀌면 같이 무너질 수 있다.
"""
import json
import os

from .us_base_simulator import USBaseSimulator, US_DEFAULT_INITIAL_CASH
from .us_calendar import us_trading_date

TOP_N = 20            # 워치리스트에 남길 상위 종목 수(보유 5 + 이탈 여유)
MAX_HOLDINGS = 5      # 실제 보유 종목 수 — US Sim1·Sim2와 동일 관례
POSITION_WEIGHT = 0.19
REBALANCE_DAYS = 20   # 리밸런스 주기(거래일). 5일 리밸런스는 같은 검증에서 더 나빴다.

WATCHLIST_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'data',
    'sim_us3_liquidity_watchlist.json')


def build_watchlist(rows) -> dict:
    """rows: [(symbol, name, avg_dollar_volume)] → 상위 TOP_N 워치리스트.

    거래대금이 없거나 0 이하인 종목은 뺀다 — 측정 실패를 0으로 취급해 '유동성
    최하위'로 줄 세우면, 조회에 실패한 종목이 조용히 후보에서 밀려날 뿐 아니라
    실패 사실 자체가 사라진다."""
    ranked = sorted(
        ((s, n, float(v)) for s, n, v in rows if v is not None and float(v) > 0),
        key=lambda x: -x[2])[:TOP_N]
    return {s: {'name': n, 'avg_dollar_volume': v, 'rank': i + 1}
            for i, (s, n, v) in enumerate(ranked)}


def save_watchlist(entries: dict, date_str: str) -> None:
    os.makedirs(os.path.dirname(WATCHLIST_PATH), exist_ok=True)
    with open(WATCHLIST_PATH, 'w', encoding='utf-8') as f:
        json.dump({'date': date_str, 'entries': entries}, f, ensure_ascii=False)


def load_watchlist(date_str: str) -> dict:
    """오늘 날짜와 일치할 때만 돌려준다(fail-closed) — US Sim1·Sim2와 동일 관례."""
    try:
        with open(WATCHLIST_PATH, encoding='utf-8-sig') as f:
            data = json.load(f)
    except Exception:
        return {}
    if not isinstance(data, dict) or data.get('date') != date_str:
        return {}
    entries = data.get('entries')
    return entries if isinstance(entries, dict) else {}


def advance_schedule(sched: dict, today: str) -> dict:
    """거래일 카운터를 하루 올린다. 같은 거래일에 여러 번 불려도 한 번만 센다
    (장중 루프는 5분마다 돈다)."""
    sched = dict(sched or {})
    last = sched.get('last_seen')
    if last is None:
        sched['elapsed'] = 0
    elif last != today:
        sched['elapsed'] = int(sched.get('elapsed', 0)) + 1
    sched['last_seen'] = today
    return sched


def mark_rebalanced(sched: dict) -> dict:
    sched = dict(sched or {})
    sched['elapsed'] = 0
    return sched


def decide_us_liquidity(view, candidates, current_prices, sched=None):
    """[US Sim3] 거래대금 상위 MAX_HOLDINGS 보유. 순수 함수. Order 리스트 반환.

    sched가 비어 있으면(첫 실행) 즉시 리밸런스한다. 그 외에는 elapsed가
    REBALANCE_DAYS에 도달했을 때만 움직인다."""
    sched = sched or {}
    if sched and int(sched.get('elapsed', 0)) < REBALANCE_DAYS:
        return []

    portfolio = view['portfolio']
    ranked = sorted(
        (s for s in candidates
         if s.get('code') and float(s.get('price', 0) or 0) > 0
         and s.get('avg_dollar_volume') is not None),
        key=lambda s: -float(s['avg_dollar_volume']))

    # 목표 = 상위부터 훑되 '1주도 못 사는' 종목은 건너뛰고 다음 순위로 채운다.
    # 주가가 포지션 예산(NAV*POSITION_WEIGHT)보다 비싼 종목이 실제로 있다
    # (BRK.A, NVR, 분할 전 BKNG 등). 이걸 그냥 두면 보유 슬롯에 구멍이 나고,
    # 기준선이 "상위 5종목"이 아니라 "상위 5종목 중 살 수 있었던 것"이 된다.
    # 랭킹 외의 판단이 아니라 매수 가능성 제약이라 잣대의 성격을 해치지 않는다.
    budget = view['nav'] * POSITION_WEIGHT
    target = []
    for s in ranked:
        if len(target) >= MAX_HOLDINGS:
            break
        if s['code'] in portfolio or int(budget / float(s['price'])) > 0:
            target.append(s)
    target_codes = {s['code'] for s in target}

    orders = []
    # 1. 상위 목록에서 밀려난 보유 종목은 전량 매도.
    for code in list(portfolio.keys()):
        if code in target_codes:
            continue
        cur = current_prices.get(code, 0)
        if cur <= 0:
            continue
        avg = portfolio[code].get('avg_price', 0)
        pr = (cur - avg) / avg * 100 if avg > 0 else 0.0
        orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                       'reason': f'[US유동성] 거래대금 상위 이탈 ({pr:+.1f}%)',
                       'cooldown': None, 'mark_partial': False})

    # 2. 목표 중 미보유는 매수. 랭킹 외의 조건은 걸지 않는다(이 심의 정체성).
    for rank, stock in enumerate(target, start=1):
        code = stock['code']
        if code in portfolio:
            continue
        price = float(stock['price'])
        qty = int(budget / price)
        if qty <= 0:
            continue
        adv = float(stock['avg_dollar_volume'])
        orders.append({'action': 'BUY', 'code': code, 'name': stock.get('name', code),
                       'price': price, 'quantity': qty, 'cooldown': None,
                       'reason': f'[US유동성] 거래대금 {rank}위 (일평균 ${adv/1e6:,.0f}M)'})
    return orders


class USLiquidityBaselineSimulator(USBaseSimulator):
    """[US Sim3] 유동성 상위 보유 — 기준선 심. 상세 배경은 모듈 docstring."""

    def __init__(self, initial_cash=US_DEFAULT_INITIAL_CASH):
        super().__init__("Us3Liquidity", initial_cash)

    def get_universe(self):
        entries = load_watchlist(us_trading_date())
        return [{'code': code, 'name': e.get('name', code),
                 'avg_dollar_volume': e.get('avg_dollar_volume'), 'rank': e.get('rank')}
                for code, e in entries.items()]

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)

        sched = self.state.get('rebalance', {})
        had_schedule = bool(sched)
        sched = advance_schedule(sched, us_trading_date())

        orders = decide_us_liquidity(self._view(current_prices), candidates,
                                     current_prices,
                                     sched=sched if had_schedule else {})
        # 카운터는 **실제로 리밸런스한 뒤에만** 시작한다. 2026-08-26 프로덕션에서
        # 워치리스트가 없어 후보 0개로 돌던 런들이 카운터를 켜 버렸고, 그 다음
        # 런부터 had_schedule=True/elapsed<REBALANCE_DAYS라 보유 0종목인 채로
        # 20거래일 동안 잠겼다 — "첫 실행은 즉시 리밸런스"라는 탈출구를 아무것도
        # 못 산 런이 소진한 것이다. 이미 돌던 카운터는 그대로 센다.
        if orders:
            self.state['rebalance'] = mark_rebalanced(sched)
        elif had_schedule:
            self.state['rebalance'] = sched

        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
