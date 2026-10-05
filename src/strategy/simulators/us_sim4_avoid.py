"""US Sim4 — 회피형 대형주 선택(나쁜 종목을 빼고 나머지를 든다).

## 왜 이런 모양인가

2026-10-06에 종목 선택 신호 55개(가격·재무·내부자·공매도·산업)를 S&P500 시점별
구성에서 검증했다. 결과가 이 심의 모양을 정했다.

- **동일가중으로 소수 종목을 고르면 신호와 무관하게 지수에 진다.** 2023~26년에
  S&P500 동일가중은 연 10.8%, SPY는 19.9%였다. 초대형주를 담지 못하면 연 9%p를
  깔고 시작한다. 그래서 **시총 상위 150 안에서** 고르고 **√시총**으로 싣는다.
- **무엇을 살지보다 무엇을 뺄지가 일관됐다.** 점수는 문헌에서 미리 정한 회피 신호
  여섯 개의 순위 평균이다 — 공매도가 몰린 종목, 이익이 현금으로 뒷받침되지 않는
  종목, 주식을 찍어 내는 종목, 자산을 급히 불리는 종목, 마진·이익이 꺾이는 종목.
- 다중검정을 통과한 단일 신호는 **공매도 잔고 일수**뿐이었다(t 3.8). 이걸 빼면
  아래 수치가 SPY 대비 +1.2%p로 내려간다.

이 파일과 `src/data/us_factors.py`를 **과거 월말마다 그대로 재생**한 결과
(2012-01~2026-08, 176개월, 편도 0.1%, 연 회전 1.1회):

    SPY 대비 연 +2.9%p (t 2.7) · 같은 데이터로 만든 시총가중 지수 대비 +2.1%p (t 2.0)
    2012~2022  SPY 대비 +0.6%p · 재구성 지수 대비 0.0%p
    2023~2026  SPY 대비 +9.8%p · 재구성 지수 대비 +8.3%p
    지수에 가장 크게 진 해 −3.0%p(2015) · 최대낙폭 −22%

## 한계 (이 심의 성과를 볼 때 반드시 같이 읽을 것)

- **초과수익이 2023년 이후에 몰려 있다.** 2012~2022는 지수와 같았다. 2023~26
  구간은 신호 정의를 고치기 전에 이미 본 구간이라 깨끗한 표본 외가 아니다.
- **공매도 잔고는 2018년부터만 있다.** 그 전 구간은 다섯 신호로만 재생했다.
- 재생 유니버스는 S&P500 구성 이력이고 운영 유니버스는 나스닥 스크리너 시총
  상위다. 폐지 종목 주가가 없어 재생 수치는 낙관 쪽으로 치우친다(재구성 지수가
  SPY를 연 0.9%p 이긴다 — 위 +2.0%p가 그걸 뺀 값이다).
- 관찰 심이다(tradeable:false). 자본은 다른 US 심과 달리 10만 달러다 — 40종목을
  1주 단위로 √시총 비중에 맞추려면 2만 달러로는 고가주를 못 산다.

## 실행 구조

EOD 배치(scripts/run_eod_sim_us.py)가 **달이 바뀔 때만** 점수를 새로 낸다. SEC
150콜과 FINRA 한 번이라 매일 돌릴 이유가 없다. 달이 같으면 직전 목록을 날짜만
바꿔 다시 쓴다. 장중 루프는 워치리스트의 `score_month`가 마지막 교체 월과 다를 때
한 번 교체하고, 그 뒤로는 보유 종목 시세만 본다.
"""
import json
import math
import os

from src.data.us_factors import SIGNALS as FACTOR_SIGNALS
from .base_simulator import log_funnel
from .us_base_simulator import USBaseSimulator
from .us_calendar import us_trading_date

INITIAL_CASH = 100_000
POOL_SIZE = 150          # 시총 상위 몇 종목 안에서 고르는가
MAX_HOLDINGS = 40
BUFFER_RANK = 80         # 보유 종목은 점수 순위가 여기 밖으로 밀려야 판다(잦은 교체 방지)
WEIGHT_CAP = 0.10
CASH_RESERVE = 0.02      # 1주 단위 반올림과 매수 순서 때문에 현금이 모자라지 않게
REWEIGHT_BAND = 0.25     # 목표 수량과 이만큼 이상 어긋난 보유분만 맞춘다
MIN_SIGNALS = 3          # 신호가 이보다 적은 종목은 점수를 매기지 않는다
# 감시목록 중 시세를 받은 비율이 이 아래면 그 사이클은 교체하지 않는다. 야후가
# 절반만 대답한 날 "받은 것 중 상위 40"을 사면 목록이 통째로 바뀐다.
MIN_QUOTE_COVERAGE = 0.9

SCORE_SIGNALS = ('si_dtc',) + tuple(FACTOR_SIGNALS)

WATCHLIST_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'data',
    'sim_us4_avoid_watchlist.json')


def _fn(funnel, code, reason, **vals):
    if funnel is None:
        return
    funnel.append({'code': code, 'reason': reason, **vals})


def days_to_cover(short_qty, avg_volume):
    """−(공매도 잔고 / 일평균 거래량). 클수록 좋다(공매도가 덜 몰렸다).
    잔고나 거래량을 모르면 None — 0주(잔고 없음)는 값이다."""
    if short_qty is None or not avg_volume or avg_volume <= 0:
        return None
    return -float(short_qty) / float(avg_volume)


def _pct_ranks(values: dict) -> dict:
    """{코드: 값} → {코드: 백분위(0~1]}. 동점은 평균 순위(pandas rank(pct=True)와 같다)."""
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    out = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[items[k][0]] = avg / n
        i = j + 1
    return out


def score_pool(rows: list[dict]) -> list[dict]:
    """rows: [{'code','name','market_cap', 신호...}] → 점수 내림차순, rank 부여.

    신호별 백분위를 평균 낸다. 신호가 빈 종목은 그 신호만 중립(0.5)으로 둔다 —
    결손을 최하위로 보면 공시 형식이 다른 회사가 이유 없이 빠진다. 대신 신호가
    MIN_SIGNALS개 미만이면 아예 점수를 매기지 않는다."""
    ranks = {}
    for sig in SCORE_SIGNALS:
        ranks[sig] = _pct_ranks({r['code']: r[sig] for r in rows if r.get(sig) is not None})
    out = []
    for r in rows:
        have = sum(1 for sig in SCORE_SIGNALS if r.get(sig) is not None)
        if have < MIN_SIGNALS:
            continue
        score = sum(ranks[sig].get(r['code'], 0.5) for sig in SCORE_SIGNALS) / len(SCORE_SIGNALS)
        out.append({**r, 'score': score, 'signals': have})
    out.sort(key=lambda r: (-r['score'], -float(r.get('market_cap') or 0)))
    for i, r in enumerate(out, start=1):
        r['rank'] = i
    return out


def build_watchlist(scored: list[dict]) -> dict:
    """점수 상위 BUFFER_RANK개만 남긴다 — 그 밖은 살 일도, 들고 있을 일도 없다."""
    return {r['code']: {'name': r.get('name', r['code']), 'rank': r['rank'],
                        'score': round(r['score'], 4), 'market_cap': r['market_cap']}
            for r in scored[:BUFFER_RANK]}


def save_watchlist(entries: dict, date_str: str, score_month: str, meta: dict | None = None) -> None:
    os.makedirs(os.path.dirname(WATCHLIST_PATH), exist_ok=True)
    with open(WATCHLIST_PATH, 'w', encoding='utf-8') as f:
        json.dump({'date': date_str, 'score_month': score_month, 'meta': meta or {},
                   'entries': entries}, f, ensure_ascii=False)


def read_watchlist_file() -> dict:
    """날짜를 보지 않고 파일 그대로. EOD 배치가 직전 목록을 이어 쓸 때만 쓴다."""
    try:
        with open(WATCHLIST_PATH, encoding='utf-8-sig') as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_watchlist(date_str: str) -> tuple[dict, str | None]:
    """(entries, score_month). 오늘 날짜와 일치할 때만(fail-closed) — 다른 US 심과 같은 관례."""
    data = read_watchlist_file()
    if data.get('date') != date_str:
        return {}, None
    entries = data.get('entries')
    if not isinstance(entries, dict) or not entries:
        return {}, None
    return entries, data.get('score_month')


def target_weights(codes: list, market_caps: dict) -> dict:
    """√시총 비중. WEIGHT_CAP으로 자른 뒤 합이 1이 되게 **한 번** 다시 나눈다.

    검증에 쓴 방식 그대로다. 한 번만 나누므로 초대형주 하나가 압도적이면 그 종목은
    상한을 조금 넘는다(2026-08 재생 구성에서 최대 10.1%)."""
    raw = {c: math.sqrt(float(market_caps[c])) for c in codes}
    total = sum(raw.values())
    w = {c: min(v / total, WEIGHT_CAP) for c, v in raw.items()}
    total = sum(w.values())
    return {c: v / total for c, v in w.items()}


def decide_us_avoid(view, entries, candidates, current_prices, funnel=None):
    """[US Sim4] 월 1회 교체. 순수 함수. (orders, complete) 반환.

    complete=False면 이번 사이클은 교체를 끝낸 것으로 치지 않는다(다음 사이클에 다시)."""
    portfolio = view['portfolio']
    priced = {}
    for c in candidates:
        code = c.get('code')
        if not code:
            _fn(funnel, '_', 'no_code')
            continue
        if float(c.get('price', 0) or 0) <= 0:
            _fn(funnel, code, 'no_price')
            continue
        priced[code] = float(c['price'])
    if len(priced) < MIN_QUOTE_COVERAGE * len(entries):
        _fn(funnel, '_gate', 'quotes_incomplete', got=len(priced), need=len(entries))
        return [], False

    # 보유 종목은 BUFFER_RANK 안에 있으면 그대로 든다. 감시목록 자체가 그 안쪽만 담는다.
    held_keep = [c for c in portfolio if c in entries]
    by_rank = sorted(entries, key=lambda c: entries[c]['rank'])
    investable = view['nav'] * (1 - CASH_RESERVE)
    caps = {c: entries[c]['market_cap'] for c in entries}
    # 1주도 못 사는 종목은 빼고 다음 순위로 채운다(US Sim3과 같은 처리). 비중이
    # 구성에 따라 달라지므로, 빠지는 종목이 없어질 때까지 다시 짠다.
    unaffordable = set()
    while True:
        keep = list(held_keep)
        cut = None
        for code in by_rank:
            if len(keep) >= MAX_HOLDINGS:
                cut = code
                break
            if code in keep or code in unaffordable or code not in priced:
                continue
            keep.append(code)
        weights = target_weights(keep, caps) if keep else {}
        drop = [c for c in keep if c not in portfolio
                and int(investable * weights[c] / priced[c]) == 0]
        if not drop:
            break
        unaffordable.update(drop)
    for code in by_rank:
        if code == cut:
            _fn(funnel, code, 'below_rank_cutoff', cap=MAX_HOLDINGS)
            break
        if code in unaffordable:
            _fn(funnel, code, 'unaffordable', price=priced[code])
        elif code not in priced:
            _fn(funnel, code, 'no_price')

    sells, buys = [], []
    for code, pos in portfolio.items():
        if code in keep:
            continue
        cur = current_prices.get(code, 0)
        if cur <= 0:
            # 값을 모르면 팔 수 없다. 이 종목 때문에 교체 전체를 미루지는 않는다 —
            # 상장폐지된 종목이면 영영 값이 안 오고, 그러면 심이 통째로 멈춘다.
            _fn(funnel, code, 'exit_no_price')
            continue
        avg = pos.get('avg_price', 0)
        pr = (cur - avg) / avg * 100 if avg > 0 else 0.0
        sells.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                      'reason': f'[US회피] 점수 {BUFFER_RANK}위 밖 이탈 ({pr:+.1f}%)',
                      'cooldown': None, 'mark_partial': False})

    for code in keep:
        price = priced.get(code) or current_prices.get(code, 0)
        if price <= 0:
            _fn(funnel, code, 'no_price')
            continue
        target = int(investable * weights[code] / price)
        held = portfolio.get(code, {}).get('quantity', 0)
        gap = target - held
        if held and abs(gap) <= REWEIGHT_BAND * max(target, 1):
            _fn(funnel, code, 'already_held')
            continue
        e = entries[code]
        if gap > 0:
            buys.append({'action': 'BUY', 'code': code, 'name': e.get('name', code),
                         'price': price, 'quantity': gap, 'cooldown': None,
                         'reason': f"[US회피] 점수 {e['rank']}위 · 목표 비중 {weights[code]*100:.1f}%"})
        elif gap < 0:
            sells.append({'action': 'SELL', 'code': code, 'price': price, 'quantity': -gap,
                          'reason': f"[US회피] 비중 축소 (목표 {weights[code]*100:.1f}%)",
                          'cooldown': None, 'mark_partial': False})
        else:
            _fn(funnel, code, 'qty_zero', price=price)
    # 매도를 먼저 내야 매수 현금이 생긴다.
    return sells + buys, True


class USAvoidSimulator(USBaseSimulator):
    """[US Sim4] 회피형 대형주 선택. 상세 배경은 모듈 docstring."""

    def __init__(self, initial_cash=INITIAL_CASH):
        super().__init__("Us4Avoid", initial_cash)

    def _pending(self):
        entries, month = load_watchlist(us_trading_date())
        if not entries or month is None or self.state.get('rebalance_month') == month:
            return {}, month
        return entries, month

    def get_universe(self):
        # 교체할 달이 아니면 빈 목록 — 장중 루프가 감시목록 80종목 시세를 2분마다
        # 받을 이유가 없다. 보유 종목 시세는 루프가 따로 받는다.
        entries, _ = self._pending()
        return [{'code': code, 'name': e.get('name', code), 'rank': e.get('rank'),
                 'market_cap': e.get('market_cap')} for code, e in entries.items()]

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        entries, month = self._pending()
        funnel = []
        orders = []
        if entries:
            orders, complete = decide_us_avoid(self._view(current_prices), entries,
                                               candidates, current_prices, funnel=funnel)
            log_funnel('US회피', candidates, funnel, orders)
            self._apply(orders, current_prices)
            if complete:
                self.state['rebalance_month'] = month
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
