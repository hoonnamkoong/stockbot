from .base_simulator import BaseSimulator, DEFAULT_INITIAL_CASH, log_funnel

_cooldown_active = BaseSimulator.cooldown_active

MAX_HOLDINGS = 5
POSITION_WEIGHT = 0.19   # 종목당 NAV 대비 비중 (전 심 통일)

CHANNEL_DAYS = 20        # 진입 채널 (원 터틀 System 1)
EXIT_DAYS = 10           # 청산 채널
ATR_STOP_MULT = 2.0      # 손절 = 진입가 - 2*ATR
MIN_SAMPLE = 10          # 거래대금 횡단면 z 최소 표본. 미달이면 신호 없음(fail-closed)
MIN_AMOUNT = 1_000_000_000



def _fn(funnel, code, reason, **vals):
    """왜 안 샀는지 한 줄 남긴다(심5·심6·심12와 같은 방식).

    심9-1은 채널 이력(range_history)과 거래대금 급증(zamt) 두 입력에 모두
    의존하는데, 둘 중 무엇이 없어서 0건인지 밖에서 구분되지 않았다.
    입력 결손과 전략 미달은 고치는 곳이 다르다.
    """
    if funnel is None:
        return
    funnel.append({'code': code, 'reason': reason, **vals})

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


def _surge_pairs(candidates):
    """[(code, 당일거래대금 / 그 종목의 평균거래대금)] — '거래대금 급증' 배수.

    2026-08-26까지는 절대 거래대금을 그대로 횡단면 z에 넣었다. 그런데 당일
    거래대금 분포는 대형주가 평균을 끌어올려 심하게 치우쳐서, z>0이 사실상
    "대형주인가" 필터로 동작한다 — 돌파했는지와 무관하게. 미국판(US Sim2)에서
    같은 코드를 실측했더니 후보 300종목 중 20일 채널을 돌파한 16종목이 **전부**
    이 게이트에서 막혔다(z -0.09 ~ -0.38).

    자기 평균 대비 배수로 바꾸면 종목 크기가 상쇄되고 '평소보다 얼마나 많이
    도는가'만 남는다. 이 배수를 다시 횡단면 z로 만드는 이유는 장중 경과시간
    때문이다 — amount는 당일 누적이라 개장 직후면 정상 종목도 배수가 작다.
    모든 후보가 같은 경과시간을 공유하므로 횡단면 z가 그 효과를 상쇄한다.

    기준선(amount_history)이 없는 종목은 **뺀다**. 0으로 두면 '측정 불가'가
    '급증 없음'으로 둔갑하고, 스크래퍼가 이 필드를 아직 안 싣는 구간에서는
    조용히 전 종목이 후보에서 사라진다(그 결손은 data_fetcher가 따로 경고한다).
    """
    out = []
    for s in candidates:
        code = s.get('code')
        hist = [a for a in (s.get('amount_history') or []) if a and a > 0]
        if not code or not hist:
            continue
        base = sum(hist) / len(hist)
        out.append((code, float(s.get('amount', 0) or 0) / base))
    return out


def _atr(hist):
    """종가 간 절대변동의 평균. base_simulator.calculate_atr과 같은 근사식이다.

    진짜 ATR은 고가-저가가 필요하다. KIS 일봉(FHKST03010100) 백필이 들어오면
    교체할 자리다. 근사 ATR은 갭을 못 보므로 실제보다 작게 나온다 → 손절이 타이트해진다.
    """
    if len(hist) < 2:
        return 0.0
    diffs = [abs(hist[i] - hist[i - 1]) for i in range(1, len(hist))]
    return sum(diffs) / len(diffs)


def decide_donchian(view, candidates, current_prices, funnel=None):
    """[Sim9-1] 돈치안 채널 돌파 결정. 순수 함수. Order 리스트 반환."""
    orders = []
    portfolio = view['portfolio']
    sold = set()
    cand_by_code = {s.get('code'): s for s in candidates if s.get('code')}
    zamt = _zmap(_surge_pairs(candidates))

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
        code = stock['code']
        if held >= MAX_HOLDINGS:
            _fn(funnel, code, 'max_holdings', held=held)
            break
        if code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            _fn(funnel, code, 'held_or_cooldown')
            continue
        raw_price, raw_amount = stock.get('price'), stock.get('amount')
        # 필드 부재와 값 미달은 다른 고장이다 — 전자는 데이터 경로, 후자는 전략.
        if raw_price is None:
            _fn(funnel, code, 'no_price_field')
            continue
        if raw_amount is None:
            _fn(funnel, code, 'no_amount_field')
            continue
        price = float(raw_price or 0)
        amount = float(raw_amount or 0)
        if price <= 0:
            _fn(funnel, code, 'no_price')
            continue
        if amount < MIN_AMOUNT:
            _fn(funnel, code, 'amount', amount=amount)
            continue
        hist = _clean(stock.get('range_history'))
        if len(hist) < CHANNEL_DAYS:
            # 채널을 못 만든다 = **입력 결손**이지 전략 미달이 아니다.
            # 이게 후보 전량이면 심이 아니라 데이터 경로를 봐야 한다.
            _fn(funnel, code, 'no_channel', days=len(hist))
            continue
        av = zamt.get(code)
        if av is None or av <= 0:
            _fn(funnel, code, 'no_amount_surge', zamt=av)
            continue

        ch_hi = max(hist[-CHANNEL_DAYS:])
        if price <= ch_hi:
            _fn(funnel, code, 'below_channel_high', price=price, high=ch_hi)
            continue
        qty = int(target_amount / price)
        if qty <= 0:
            _fn(funnel, code, 'qty_zero', price=price, target=target_amount)
            continue
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
    - 진입: 20일 채널(range_history 종가) 상단 돌파 + 거래대금 급증(자기 평균
      대비 배수의 횡단면 z > 0, _surge_pairs 참고) + 거래대금>=10억
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

    def __init__(self, initial_cash=DEFAULT_INITIAL_CASH):
        super().__init__("Donchian", initial_cash)

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        funnel = []
        orders = decide_donchian(self._view(current_prices), candidates,
                                 current_prices, funnel=funnel)
        log_funnel('돈치안', candidates, funnel, orders)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
