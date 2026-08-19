from .base_simulator import BaseSimulator

_cooldown_active = BaseSimulator.cooldown_active

MAX_HOLDINGS = 5
POSITION_WEIGHT = 0.19       # 종목당 NAV 대비 비중 (전 심 통일)
MIN_AMOUNT = 1_000_000_000   # 거래대금 최소 문턱

STOP_PCT = -7.5              # 미너비니의 시그니처 손절폭(7~8%)의 중간값
MA_EXIT_WINDOW = 50          # 50일선 이탈 시 청산(추세 종료 신호)

MIN_ABOVE_52W_LOW_PCT = 30.0   # 52주 저가 대비 최소 상승폭
MAX_BELOW_52W_HIGH_PCT = 25.0  # 52주 고가 대비 최대 하락폭
MA200_TREND_LOOKBACK = 20      # 200일선 상승 추세 판정에 쓰는 과거 시점(약 1개월 전)

MIN_EPS_GROWTH_YOY = 20.0     # SEPA 실적 가속 필터 — EPS 전년동기대비
MIN_REVENUE_GROWTH_YOY = 15.0  # SEPA 실적 가속 필터 — 매출 전년동기대비

CONTRACTION_WINDOW = 10       # VCP 압축 판정 구간(최근 vs 그 이전)
PIVOT_WINDOW = 20             # 돌파 기준 최근 고점 탐색 구간
CONTRACTION_RATIO = 0.7       # 최근 구간 변동폭이 이전 구간의 70% 미만이면 압축으로 본다


def _sma(closes: list[float], window: int) -> float | None:
    """단순이동평균. 표본이 모자라면 None(지어내지 않는다)."""
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _trend_template_ok(price: float, closes: list[float],
                       w52_hgpr: float, w52_lwpr: float) -> bool:
    """미너비니 추세 템플릿(간소화 6항목 — 상대강도 순위는 횡단면 데이터가
    필요해 V1에서 뺐다. docstring 참고).

    1. 종가 > MA150 > MA200 (정배열)
    2. MA50 > MA150 및 MA50 > MA200
    3. 종가 > MA50
    4. MA200이 약 한 달 전보다 높다(상승 추세)
    5. 52주 저가 대비 30%+ 상승
    6. 52주 고가 대비 25% 이내
    """
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


def _vcp_breakout(price: float, closes: list[float]) -> bool:
    """변동성 수축(VCP) 후 돌파. 최근 CONTRACTION_WINDOW일의 변동폭(%)이
    그 이전 같은 길이 구간보다 눈에 띄게 좁아졌고(압축), 오늘 종가가 최근
    PIVOT_WINDOW일 고점을 넘었으면(돌파) 참.

    closes는 **당일을 포함하지 않는** 과거 종가여야 한다(Sim9-1과 같은 전제) —
    당일이 섞이면 pivot_hi가 항상 price 이상이라 돌파가 정의상 불가능해진다.
    """
    need = max(CONTRACTION_WINDOW * 2, PIVOT_WINDOW)
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
    contracting = recent_range < prior_range * CONTRACTION_RATIO

    pivot_hi = max(closes[-PIVOT_WINDOW:])
    breakout = price > pivot_hi
    return contracting and breakout


def decide_minervini(view, candidates, current_prices):
    """[Sim11] 미너비니 SEPA/VCP 결정. 순수 함수. Order 리스트 반환.

    candidates의 각 원소는 EOD 러너가 미리 채워준다: price, amount,
    daily_closes(당일 미포함 과거 종가, 오래된→최신), w52_hgpr, w52_lwpr,
    eps_growth_yoy(없으면 결손), revenue_growth_yoy.
    """
    orders = []
    portfolio = view['portfolio']
    sold = set()
    cand_by_code = {s['code']: s for s in candidates if s.get('code')}

    # 1. 청산 — 하드손절 / 50일선 이탈(추세 종료)
    for code in list(portfolio.keys()):
        p = portfolio[code]
        cur = current_prices.get(code, 0)
        avg = p.get('avg_price', 0)
        if cur <= 0 or avg <= 0:
            continue
        pr = (cur - avg) / avg * 100

        if pr <= STOP_PCT:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[미너비니] 손절 ({pr:+.1f}%)",
                           'cooldown': 3, 'mark_partial': False})
            sold.add(code); continue

        stock = cand_by_code.get(code)
        closes = (stock or {}).get('daily_closes') or []
        ma = _sma(closes, MA_EXIT_WINDOW)
        if ma is not None and cur < ma:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[미너비니] {MA_EXIT_WINDOW}일선 이탈 ({ma:,.0f} 하회, {pr:+.1f}%)",
                           'cooldown': 3, 'mark_partial': False})
            sold.add(code); continue

    # 2. 진입 — 추세 템플릿 + 실적 가속 + VCP 돌파, 전부 통과해야 산다.
    target_amount = view['nav'] * POSITION_WEIGHT
    held = len([c for c in portfolio if c not in sold])
    for stock in candidates:
        if held >= MAX_HOLDINGS:
            break
        code = stock.get('code')
        if not code or code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            continue
        price = float(stock.get('price', 0) or 0)
        amount = float(stock.get('amount', 0) or 0)
        if price <= 0 or amount < MIN_AMOUNT:
            continue

        closes = stock.get('daily_closes') or []
        w52_hgpr = float(stock.get('w52_hgpr', 0) or 0)
        w52_lwpr = float(stock.get('w52_lwpr', 0) or 0)
        if not _trend_template_ok(price, closes, w52_hgpr, w52_lwpr):
            continue

        eps_g = stock.get('eps_growth_yoy')
        rev_g = stock.get('revenue_growth_yoy')
        if eps_g is None or eps_g < MIN_EPS_GROWTH_YOY:
            continue
        if rev_g is None or rev_g < MIN_REVENUE_GROWTH_YOY:
            continue

        if not _vcp_breakout(price, closes):
            continue

        qty = int(target_amount / price)
        if qty > 0:
            orders.append({'action': 'BUY', 'code': code, 'name': stock.get('name', code),
                           'price': price, 'quantity': qty, 'cooldown': None,
                           'reason': f"[미너비니] VCP 돌파 (EPS+{eps_g:.0f}% 매출+{rev_g:.0f}%)"})
            held += 1
    return orders


class MinerviniTrendSimulator(BaseSimulator):
    """
    [Sim 11] 미너비니 추세형 (SEPA / VCP — Trend Template)
    - 레퍼런스: Mark Minervini. US Investing Championship 1997 +155%, 2021 +334.8%(대회 감사·검증).
      다만 그 수익률은 레버리지·집중·재량판단이 섞인 개인 성과다 — 이 심은
      문서화된 규칙(트렌드 템플릿+실적 가속+VCP)만 기계적으로 따르므로 같은
      수익률을 재현한다는 보장은 없다. [[sim0-nowcast-redesign]]류 다른 심들과
      마찬가지로 페이퍼로 실측해서 검증할 대상이다.
    - 진입(전부 충족): ① 추세 템플릿(정배열 MA50>MA150>MA200, 종가>MA50,
      MA200 상승 추세, 52주 저가 대비 +30%, 52주 고가 대비 -25% 이내)
      ② 실적 가속(EPS 전년동기 +20%↑, 매출 전년동기 +15%↑)
      ③ VCP: 최근 10일 변동폭이 이전 10일의 70% 미만(압축) + 최근 20일 고점 돌파
    - 청산: 하드손절 -7.5% / 50일선 이탈(추세 종료 신호, 고정 익절 없음 — 승자는 끝까지 탄다)
    - 상대강도(RS) 순위는 V1에서 뺐다 — 횡단면 전체 유니버스의 기간수익률
      랭킹이 필요한데 지금 유니버스(top100 비ETF)가 그 모집단으로 적절한지
      미검증이라 다음 버전 과제로 남긴다.
    - **실행 위치: 장중 루프가 아니라 마감 후 1회**(IS_EOD). scripts/run_eod_sims.py가
      돈다 — Sim9-1과 같은 이유(50/150/200일선·분기 실적은 장중에 안 바뀐다).
      필요 데이터(200일+ 일봉, 분기 EPS/매출성장률)는 2026-08-20에 KIS 실측
      확인: `KISDataProvider.get_daily_history`/`get_earnings_growth`.
    - ⚠ daily_closes는 **당일 미포함**이어야 한다(Sim9-1과 같은 함정) — EOD
      러너가 명시적으로 뺀다.
    """
    IS_EOD = True

    def __init__(self, initial_cash=3000000):
        super().__init__("Minervini", initial_cash)

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        orders = decide_minervini(self._view(current_prices), candidates, current_prices)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
