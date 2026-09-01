"""US Sim1 — 미너비니 추세형(SEPA/VCP), 국내 Sim11의 미국 이식.

로직(추세 템플릿·VCP 압축·pivot 돌파·손절·50일선 이탈)은 국내 Sim11
(sim11_minervini.py)과 동일하다 — 통화·데이터 소스만 다르다. 국내 파이프라인
독립 원칙 때문에 sim11_minervini.py를 import하지 않고 그대로 옮겨 적는다.

EOD 배치(scripts/run_eod_sim_us.py)가 추세 템플릿+실적 가속+VCP 압축을 하루
1회 계산해 워치리스트에 남기고, 실제 매수/매도는 장중 루프
(scripts/us_trade_loop.py)가 실시간에 가까운 가격으로 판단한다
(program-trading-parity 원칙 — 국내와 동일하게 룩어헤드를 피한다).
"""
import json
import os

from .us_base_simulator import USBaseSimulator, US_DEFAULT_INITIAL_CASH
from .us_calendar import us_trading_date, next_us_trading_date  # noqa: F401
from .base_simulator import BaseSimulator

_cooldown_active = BaseSimulator.cooldown_active

MAX_HOLDINGS = 5
POSITION_WEIGHT = 0.19
MIN_AMOUNT = 10_000_000  # 미국 대형주 유동성 기준 일일 거래대금 최소 문턱(USD)

STOP_PCT = -7.5
MA_EXIT_WINDOW = 50

MIN_ABOVE_52W_LOW_PCT = 30.0
MAX_BELOW_52W_HIGH_PCT = 25.0
MA200_TREND_LOOKBACK = 20

MIN_EPS_GROWTH_YOY = 20.0
MIN_REVENUE_GROWTH_YOY = 15.0

CONTRACTION_WINDOW = 10
PIVOT_WINDOW = 20
CONTRACTION_RATIO = 0.7

WATCHLIST_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'data',
    'sim_us1_minervini_watchlist.json')


def _sma(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _trend_template_ok(price: float, closes: list[float],
                       w52_hgpr: float, w52_lwpr: float) -> bool:
    ma50 = _sma(closes, 50)
    ma150 = _sma(closes, 150)
    ma200 = _sma(closes, 200)
    if ma50 is None or ma150 is None or ma200 is None:
        return False
    if len(closes) < 200 + MA200_TREND_LOOKBACK:
        return False
    ma200_prior = _sma(closes[:-MA200_TREND_LOOKBACK], 200)
    if ma200_prior is None:
        return False
    if not (price > ma150 > ma200):
        return False
    if not (ma50 > ma150 and ma50 > ma200):
        return False
    if not (price > ma50):
        return False
    if not (ma200 > ma200_prior):
        return False
    if w52_lwpr <= 0 or w52_hgpr <= 0:
        return False
    if price < w52_lwpr * (1 + MIN_ABOVE_52W_LOW_PCT / 100):
        return False
    if price < w52_hgpr * (1 - MAX_BELOW_52W_HIGH_PCT / 100):
        return False
    return True


def _vcp_contracting(closes: list[float]) -> bool:
    need = CONTRACTION_WINDOW * 2
    if len(closes) < need:
        return False
    recent = closes[-CONTRACTION_WINDOW:]
    prior = closes[-CONTRACTION_WINDOW * 2:-CONTRACTION_WINDOW]
    if recent[-1] <= 0 or prior[-1] <= 0:
        return False
    recent_range = (max(recent) - min(recent)) / recent[-1]
    prior_range = (max(prior) - min(prior)) / prior[-1]
    if prior_range <= 0:
        return False
    return recent_range < prior_range * CONTRACTION_RATIO


def build_watchlist_entry(stock: dict) -> dict | None:
    """stock: {'symbol','price','daily_closes'(오늘 미포함),'w52_hgpr','w52_lwpr',
    'eps_growth_yoy','revenue_growth_yoy'}. 자격 미달이면 None."""
    price = float(stock.get('price', 0) or 0)
    daily_closes = stock.get('daily_closes') or []
    if price <= 0:
        return None

    w52_hgpr = float(stock.get('w52_hgpr', 0) or 0)
    w52_lwpr = float(stock.get('w52_lwpr', 0) or 0)
    if not _trend_template_ok(price, daily_closes, w52_hgpr, w52_lwpr):
        return None

    eps_g = stock.get('eps_growth_yoy')
    rev_g = stock.get('revenue_growth_yoy')
    if eps_g is None or eps_g < MIN_EPS_GROWTH_YOY:
        return None
    if rev_g is None or rev_g < MIN_REVENUE_GROWTH_YOY:
        return None

    closes_through_today = daily_closes + [price]
    if not _vcp_contracting(closes_through_today):
        return None
    ma50 = _sma(closes_through_today, MA_EXIT_WINDOW)
    if ma50 is None:
        return None

    return {
        'name': stock.get('name', stock.get('symbol', '')),
        'pivot_price': max(closes_through_today[-PIVOT_WINDOW:]),
        'ma50': ma50,
        'avg_dollar_volume': stock.get('avg_dollar_volume'),
    }


def save_watchlist(entries: dict[str, dict], date_str: str) -> None:
    os.makedirs(os.path.dirname(WATCHLIST_PATH), exist_ok=True)
    with open(WATCHLIST_PATH, 'w', encoding='utf-8') as f:
        json.dump({'date': date_str, 'entries': entries}, f, ensure_ascii=False)


def load_watchlist(date_str: str) -> dict[str, dict]:
    """오늘 날짜와 일치할 때만 돌려준다(fail-closed) — 국내 Sim11과 동일 관례."""
    try:
        with open(WATCHLIST_PATH, encoding='utf-8-sig') as f:
            data = json.load(f)
    except Exception:
        return {}
    if not isinstance(data, dict) or data.get('date') != date_str:
        return {}
    entries = data.get('entries')
    return entries if isinstance(entries, dict) else {}


def decide_us_minervini(view, candidates, current_prices):
    """국내 Sim11의 decide_minervini와 동일 로직(통화 무관 순수 함수).

    유동성 문턱(MIN_AMOUNT)은 candidates의 실시간 amount가 아니라 워치리스트에
    실려온 avg_dollar_volume(EOD 배치가 계산한 최근 평균거래대금)으로 판정한다.
    실시간 amount는 당일 누적 거래량 기준이라 개장 직후 몇 시간은 실제로 유동성이
    충분한 종목도 낮게 잡혀 진입이 스퓨리어스하게 막힌다(2026-08-24 리뷰에서 발견)."""
    orders = []
    portfolio = view['portfolio']
    sold = set()
    cand_by_code = {s['code']: s for s in candidates if s.get('code')}

    for code in list(portfolio.keys()):
        p = portfolio[code]
        cur = current_prices.get(code, 0)
        avg = p.get('avg_price', 0)
        if cur <= 0 or avg <= 0:
            continue
        pr = (cur - avg) / avg * 100

        if pr <= STOP_PCT:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[US미너비니] 손절 ({pr:+.1f}%)",
                           'cooldown': 3, 'mark_partial': False})
            sold.add(code); continue

        ma50 = (cand_by_code.get(code) or {}).get('ma50')
        if ma50 is not None and cur < ma50:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[US미너비니] {MA_EXIT_WINDOW}일선 이탈 ({ma50:,.2f} 하회, {pr:+.1f}%)",
                           'cooldown': 3, 'mark_partial': False})
            sold.add(code); continue

    target_amount = view['nav'] * POSITION_WEIGHT
    held = len([c for c in portfolio if c not in sold])
    for stock in candidates:
        if held >= MAX_HOLDINGS:
            break
        code = stock.get('code')
        if not code or code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            continue

        price = float(stock.get('price', 0) or 0)
        avg_dollar_volume = stock.get('avg_dollar_volume')
        pivot = stock.get('pivot_price')
        if price <= 0 or pivot is None or avg_dollar_volume is None or avg_dollar_volume < MIN_AMOUNT:
            continue
        if price <= pivot:
            continue

        qty = int(target_amount / price)
        if qty > 0:
            orders.append({'action': 'BUY', 'code': code, 'name': stock.get('name', code),
                           'price': price, 'quantity': qty, 'cooldown': None,
                           'reason': f"[US미너비니] 실시간 pivot 돌파 (${pivot:,.2f} 상회)"})
            held += 1
    return orders


class USMinerviniSimulator(USBaseSimulator):
    """[US Sim1] 미너비니 추세형 — 국내 Sim11 이식. 상세 배경은 위 모듈 docstring."""

    def __init__(self, initial_cash=US_DEFAULT_INITIAL_CASH):
        super().__init__("Us1Minervini", initial_cash)

    def get_universe(self):
        today = us_trading_date()
        entries = load_watchlist(today)
        return [
            {'code': code, 'name': e.get('name', code),
             'pivot_price': e.get('pivot_price'), 'ma50': e.get('ma50'),
             'avg_dollar_volume': e.get('avg_dollar_volume')}
            for code, e in entries.items()
        ]

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        orders = decide_us_minervini(self._view(current_prices), candidates, current_prices)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
