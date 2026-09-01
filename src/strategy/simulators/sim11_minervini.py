import json
import os

from .base_simulator import BaseSimulator, get_kst_now, DEFAULT_INITIAL_CASH

_cooldown_active = BaseSimulator.cooldown_active

MAX_HOLDINGS = 5
POSITION_WEIGHT = 0.19       # 종목당 NAV 대비 비중 (전 심 통일)
MIN_AMOUNT = 1_000_000_000   # 거래대금 최소 문턱(매수 시점 실시간 값으로 확인)

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

# EOD 배치(scripts/run_eod_sims.py)가 쓰고, get_universe()가 읽는다. 하루에
# 한 번만 갱신되는 파일이라 다른 심의 state_file과 달리 db-data 배포 목록에
# 별도로 넣어야 한다(eod_data.yml).
WATCHLIST_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'data', 'sim11_watchlist.json')


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


def _vcp_contracting(closes: list[float]) -> bool:
    """변동성 수축(VCP) 판정만 한다 — 돌파(가격 비교)는 여기서 안 본다.

    2026-08-20 재설계: 예전엔 "오늘 종가가 pivot을 넘었나"까지 이 함수가
    판정했는데, 그건 EOD 배치(장 마감 후)가 **이미 끝난 오늘 종가**로
    매수 여부를 정하는 꼴이었다 — 실제로 그 가격에 살 수 있는 시점이
    지나 있다(backtest-lookahead-trap과 같은 함정, program-trading-parity
    위반). 돌파 판정은 이제 decide_minervini가 **장중 실시간가**로 한다.
    이 함수는 압축 여부만 판정해 감시 목록(watchlist) 등재 자격을 정한다.

    closes는 오늘까지 포함한 종가열이어야 한다(watchlist는 내일 쓸 것이므로
    오늘이 이미 '과거'다).
    """
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
    """감시 목록 항목 하나를 만든다. 자격 미달이면 None.

    stock은 scripts.run_eod_sims.candidates_from_kis_live가 주는 형태다:
    price(오늘 종가), daily_closes(오늘 미포함 과거 종가), w52_hgpr, w52_lwpr,
    eps_growth_yoy(없으면 결손), revenue_growth_yoy.

    반환하는 pivot_price·ma50은 **내일부터** 쓸 기준이다 — 오늘을 '이미 지난
    거래일'로 넣어 계산한다(closes_through_today = daily_closes + [price]).
    """
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
        'name': stock.get('name', stock.get('code', '')),
        'pivot_price': max(closes_through_today[-PIVOT_WINDOW:]),
        'ma50': ma50,
    }


def save_watchlist(entries: dict[str, dict], date_str: str) -> None:
    os.makedirs(os.path.dirname(WATCHLIST_PATH), exist_ok=True)
    with open(WATCHLIST_PATH, 'w', encoding='utf-8') as f:
        json.dump({'date': date_str, 'entries': entries}, f, ensure_ascii=False)


def load_watchlist(date_str: str) -> dict[str, dict]:
    """오늘 날짜와 일치할 때만 돌려준다(fail-closed).

    낡은 감시 목록을 오늘 걸로 오인하면 며칠 전 pivot_price로 잘못된 시점에
    사게 된다 — status.json 신선도 검사 없이 조용히 옛 값을 쓰던 Sim8의
    함정과 같은 유형이다.
    """
    try:
        with open(WATCHLIST_PATH, encoding='utf-8-sig') as f:
            data = json.load(f)
    except Exception:
        return {}
    if not isinstance(data, dict) or data.get('date') != date_str:
        return {}
    entries = data.get('entries')
    return entries if isinstance(entries, dict) else {}


def decide_minervini(view, candidates, current_prices):
    """[Sim11] 미너비니 SEPA/VCP 결정. 순수 함수. Order 리스트 반환.

    candidates는 get_universe()가 준 감시 목록(code, name, pivot_price, ma50)에
    _enrich_universe가 실시간 price·amount를 채운 것이다 — 무거운 계산
    (추세 템플릿·실적 가속·VCP 압축)은 이미 EOD 배치에서 끝났고, 여기서는
    **실시간가가 pivot을 넘는지**만 본다(program-trading-parity: 실제로
    체결 가능한 가격으로만 판단).
    """
    orders = []
    portfolio = view['portfolio']
    sold = set()
    cand_by_code = {s['code']: s for s in candidates if s.get('code')}

    # 1. 청산 — 하드손절(가격만으로 판단) / 50일선 이탈(감시 목록의 ma50, 실시간가와 비교)
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

        ma50 = (cand_by_code.get(code) or {}).get('ma50')
        if ma50 is not None and cur < ma50:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[미너비니] {MA_EXIT_WINDOW}일선 이탈 ({ma50:,.0f} 하회, {pr:+.1f}%)",
                           'cooldown': 3, 'mark_partial': False})
            sold.add(code); continue

    # 2. 진입 — 감시 목록 종목의 실시간가가 pivot_price를 넘는 순간 산다.
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
        pivot = stock.get('pivot_price')
        if price <= 0 or pivot is None or amount < MIN_AMOUNT:
            continue
        if price <= pivot:
            continue

        qty = int(target_amount / price)
        if qty > 0:
            orders.append({'action': 'BUY', 'code': code, 'name': stock.get('name', code),
                           'price': price, 'quantity': qty, 'cooldown': None,
                           'reason': f"[미너비니] 실시간 pivot 돌파 ({pivot:,.0f} 상회)"})
            held += 1
    return orders


class MinerviniTrendSimulator(BaseSimulator):
    """
    [Sim 11] 미너비니 추세형 (SEPA / VCP — Trend Template)
    - 레퍼런스: Mark Minervini. US Investing Championship 1997 +155%, 2021 +334.8%(대회 감사·검증).
      다만 그 수익률은 레버리지·집중·재량판단이 섞인 개인 성과다 — 이 심은
      문서화된 규칙(트렌드 템플릿+실적 가속+VCP)만 기계적으로 따르므로 같은
      수익률을 재현한다는 보장은 없다.

    - **2026-08-20 재설계: EOD 판단 + EOD 체결 → EOD 판단 + 장중 체결.**
      처음 버전은 마감 후 배치가 그날 종가로 사고팔았다 — 이미 지난
      가격으로 "샀다"고 기록하는 룩어헤드였고(backtest-lookahead-trap),
      실전으로 승격해도 그 가격에 주문을 낼 방법이 없었다
      (program-trading-parity-mandate 위반). 이제 무거운 계산(추세
      템플릿·실적 가속·VCP 압축, 종목당 KIS 3콜)만 EOD 배치가 하루 1회
      돌려 **감시 목록**(WATCHLIST_PATH)에 남기고, 실제 매수/매도는 이
      심이 **장중 1분 루프**(다른 버즈 불필요 심들과 같은 경로)에서
      실시간가로 한다.
    - 진입: 감시 목록에 있고(전날 밤 이미 추세 템플릿+실적 가속+VCP 압축
      통과), 실시간가가 그때 계산한 pivot_price(20일 고점)를 넘으면 산다.
    - 청산: 하드손절 -7.5%(실시간가) / 실시간가가 감시 목록의 ma50 밑으로
      내려가면(추세 종료). 고정 익절 없음 — 승자는 끝까지 탄다.
    - get_universe()는 감시 목록만 돌려주고 **price를 채우지 않는다** —
      _enrich_universe(trade_engine.py)가 실시간 KIS 시세로 채운다(Sim6와
      같은 공유 보강 경로를 그대로 탄다). 오늘 날짜 감시 목록이 없으면
      빈 유니버스(폴백 없음 — 낡은 pivot으로 사지 않는다).
    - 상대강도(RS) 순위는 V1에서 뺐다 — 횡단면 전체 유니버스의 기간수익률
      랭킹이 필요한데 지금 유니버스(top100 비ETF)가 그 모집단으로 적절한지
      미검증이라 다음 버전 과제로 남긴다.
    - 감시 목록 생성: `scripts/run_eod_sims.py`가 하루 1회(장 마감 후) 돈다.
      필요 데이터(200일+ 일봉, 분기 EPS/매출성장률)는 2026-08-20에 KIS 실측
      확인: `KISDataProvider.get_daily_history`/`get_earnings_growth`.
    """

    def __init__(self, initial_cash=DEFAULT_INITIAL_CASH):
        super().__init__("Minervini", initial_cash)

    def get_universe(self):
        today = get_kst_now().strftime('%Y%m%d')
        entries = load_watchlist(today)
        return [
            {'code': code, 'name': e.get('name', code),
             'pivot_price': e.get('pivot_price'), 'ma50': e.get('ma50')}
            for code, e in entries.items()
        ]

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        orders = decide_minervini(self._view(current_prices), candidates, current_prices)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
