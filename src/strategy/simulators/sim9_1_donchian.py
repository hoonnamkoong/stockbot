from .base_simulator import BaseSimulator

_cooldown_active = BaseSimulator.cooldown_active

MAX_HOLDINGS = 6
POSITION_WEIGHT = 0.15   # 종목당 NAV 대비 비중 (전 심 통일)

CHANNEL_DAYS = 20        # 진입 채널 (원 터틀 System 1)
EXIT_DAYS = 10           # 청산 채널
ATR_STOP_MULT = 2.0      # 손절 = 진입가 - 2*ATR
MIN_SAMPLE = 10          # 거래대금 횡단면 z 최소 표본. 미달이면 신호 없음(fail-closed)
MIN_AMOUNT = 1_000_000_000


def _clean(range_history):
    return [h for h in (range_history or []) if h and h > 0]


def _zmap(pairs):
    """[(code, value)] → {code: z}. 표본 부족·분산 0이면 빈 dict(=신호 없음)."""
    vals = [v for _, v in pairs]
    n = len(vals)
    if n < MIN_SAMPLE:
        return {}
    mu = sum(vals) / n
    sd = (sum((v - mu) ** 2 for v in vals) / n) ** 0.5
    if sd <= 0:
        return {}
    return {c: (v - mu) / sd for c, v in pairs}


def _atr(hist):
    """종가 간 절대변동의 평균. base_simulator.calculate_atr과 같은 근사식이다.

    진짜 ATR은 고가-저가가 필요하다. KIS 일봉(FHKST03010100) 백필이 들어오면
    교체할 자리다. 근사 ATR은 갭을 못 보므로 실제보다 작게 나온다 → 손절이 타이트해진다.
    """
    if len(hist) < 2:
        return 0.0
    diffs = [abs(hist[i] - hist[i - 1]) for i in range(1, len(hist))]
    return sum(diffs) / len(diffs)


def decide_donchian(view, candidates, current_prices):
    """[Sim9-1] 돈치안 채널 돌파 결정. 순수 함수. Order 리스트 반환."""
    orders = []
    portfolio = view['portfolio']
    sold = set()
    cand_by_code = {s.get('code'): s for s in candidates if s.get('code')}
    zamt = _zmap([(s['code'], float(s.get('amount', 0) or 0))
                  for s in candidates if s.get('code')])

    # 1. 청산 — 10일 채널 이탈 또는 2*ATR 손절. 고정 익절 없음(터틀은 추세를 끝까지 탄다).
    for code in list(portfolio.keys()):
        p = portfolio[code]
        cur = current_prices.get(code, 0)
        avg = p.get('avg_price', 0)
        if cur <= 0 or avg <= 0:
            continue
        pr = (cur - avg) / avg * 100

        hist = _clean((cand_by_code.get(code) or {}).get('range_history'))
        if len(hist) >= 2:
            stop = avg - ATR_STOP_MULT * _atr(hist[-CHANNEL_DAYS:])
            if cur <= stop:
                orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                               'reason': f"[돈치안] 2*ATR 손절 ({pr:+.1f}%)",
                               'cooldown': 3, 'mark_partial': False})
                sold.add(code); continue

        if len(hist) >= EXIT_DAYS:
            ch_lo = min(hist[-EXIT_DAYS:])
            if cur < ch_lo:
                orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                               'reason': f"[돈치안] {EXIT_DAYS}일 채널 이탈 ({ch_lo:,.0f} 하회, {pr:+.1f}%)",
                               'cooldown': 1, 'mark_partial': False})
                sold.add(code); continue

    # 2. 진입 — 20일 채널 상단 돌파 + 거래대금 동반.
    # Sim5와 같은 range_history로 정반대 방향을 실험한다(저점 매수 vs 박스 탈출).
    target_amount = view['nav'] * POSITION_WEIGHT
    held = len([c for c in portfolio if c not in sold])
    for stock in candidates:
        if held >= MAX_HOLDINGS:
            break
        code = stock['code']
        if code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            continue
        price = float(stock.get('price', 0) or 0)
        amount = float(stock.get('amount', 0) or 0)
        if price <= 0 or amount < MIN_AMOUNT:
            continue
        hist = _clean(stock.get('range_history'))
        if len(hist) < CHANNEL_DAYS:
            continue
        av = zamt.get(code)
        if av is None or av <= 0:
            continue

        ch_hi = max(hist[-CHANNEL_DAYS:])
        if price > ch_hi:
            qty = int(target_amount / price)
            if qty > 0:
                orders.append({'action': 'BUY', 'code': code, 'name': stock.get('name', code),
                               'price': price, 'quantity': qty, 'cooldown': None,
                               'reason': f"[돈치안] {CHANNEL_DAYS}일 채널 돌파 ({ch_hi:,.0f} 상회, 거래대금z {av:+.1f})"})
                held += 1
    return orders


class DonchianBreakoutSimulator(BaseSimulator):
    """
    [Sim 9-1] 돈치안 채널 돌파 (Turtle)
    - 레퍼런스: Richard Dennis & William Eckhardt 터틀 트레이딩 실험(1983).
    - 심9(갭소진)와 성격이 정반대다. 심9는 1일 역추세, 심9-1은 다일 추세추종.
      묶인 이유는 '차트 데이터 계열'뿐이라 나중에 독립 번호로 옮기는 게 자연스럽다.
    - 진입: 20일 채널(range_history 종가) 상단 돌파 + 거래대금 횡단면 z > 0 + 거래대금>=10억
    - 청산: 10일 채널 저점 이탈 / 진입가 - 2*ATR 손절. 고정 익절 없음.
    - Sim5와 같은 `range_history`를 정반대 방향으로 쓴다(Sim5는 채널 저점 매수).
    - **실행 위치: 장중 루프가 아니라 마감 후 1회**(IS_EOD). scripts/run_eod_sims.py가
      eod_data.yml의 ohlcv_top100.csv로 돌린다 — 백테스트와 같은 유니버스·같은 데이터다.
      장중 버즈 유니버스에서는 진입이 구조적으로 불가능했다(2026-07-29 실측): 거래대금
      z>0을 통과하는 종목이 28개 중 3개뿐인데 전부 초대형주라 20일 채널을 안 뚫고
      (0.53~0.72), 채널을 뚫는 소형주는 z에서 걸린다. 두 조건의 교집합이 비어 있었다.
      게이트를 스케일 무관 지표로 바꾸는 안은 백테스트가 반증했다 — 절대 거래대금 z가
      하던 일은 '거래량 급증 탐지'가 아니라 '유동성 큰 종목 선호'였다.
    - ⚠ 원 터틀은 고가/저가 기준인데 여기서는 종가 기준이다(보유 데이터의 한계).
      종가 돌파가 고가 돌파보다 엄격하므로 신호가 덜 나는 쪽으로 보수적이다.
    - ⚠ range_history는 **직전** 20일이어야 한다. 당일 종가가 들어가면 max(채널)이
      당일 종가 이상이라 돌파가 정의상 성립하지 않는다. EOD 러너가 명시적으로 뺀다.
    """
    IS_EOD = True

    def __init__(self, initial_cash=3000000):
        super().__init__("Donchian", initial_cash)

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        orders = decide_donchian(self._view(current_prices), candidates, current_prices)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
