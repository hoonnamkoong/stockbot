from datetime import datetime

from .base_simulator import BaseSimulator, get_kst_now

# base 순수 헬퍼(Task 3 @staticmethod) 재사용
_parse_change_rate = BaseSimulator.parse_change_rate
_cooldown_active = BaseSimulator.cooldown_active

MAX_HOLDINGS = 6
POSITION_WEIGHT = 0.15  # 종목당 NAV 대비 비중 (0.15 × 6 = 최대 90% 투입)

# 레인지 채널 파라미터 (백테스트로 확정)
MIN_HISTORY = 10          # 채널 산출 최소 일수
MIN_WIDTH_PCT = 8.0       # 채널 폭 하한(%): 미달=수수료 대비 무의미 셋업 → 스킵
LOW_ZONE = 0.03           # 채널 저점 +3% 이내에서만 진입
TRAIL_ARM_RATIO = 0.98    # 고점(peak)이 채널 상단의 98% 도달 시 트레일링 발동
TRAIL_CALLBACK_PCT = 2.0  # 발동 후 고점 대비 -2% 하락 시 청산
STOP_PCT = -3.0           # 하드 손절
TIMEOUT_DAYS = 7          # 타임 스탑
MIN_AMOUNT = 1_000_000_000


def _channel(range_history):
    """range_history(20일 종가) → (low, high, width_pct). 이력 부족 시 None."""
    hist = [h for h in (range_history or []) if h and h > 0]
    if len(hist) < MIN_HISTORY:
        return None
    low, high = min(hist), max(hist)
    if low <= 0:
        return None
    return low, high, (high - low) / low * 100


def decide_sideways(view, candidates, current_prices):
    """[Sim5] 레인지 저점 진입 + 트레일링 청산 결정. 순수 함수. Order 리스트 반환."""
    orders = []
    portfolio = view['portfolio']
    today = get_kst_now().date()
    sold = set()
    cand_by_code = {s.get('code'): s for s in candidates}

    # 1. 청산: 손절 / 트레일링(peak가 채널상단 근접 시 발동) / 타임스탑. 고정 익절 없음.
    for code in list(portfolio.keys()):
        p = portfolio[code]
        cur = current_prices.get(code, 0)
        if cur <= 0:
            continue
        avg = p.get('avg_price', 0)
        if avg <= 0:
            continue
        pr = (cur - avg) / avg * 100

        if pr <= STOP_PCT:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[레인지] 하드 손절 ({pr:.1f}%)", 'cooldown': 3, 'mark_partial': False})
            sold.add(code); continue

        # 트레일링: 고점이 채널 상단에 근접(=상단 스윙/돌파)했을 때만 발동, 콜백 시 잠금
        peak = p.get('peak_price', avg)
        ch = _channel((cand_by_code.get(code) or {}).get('range_history'))
        if ch and peak >= ch[1] * TRAIL_ARM_RATIO:
            if cur <= peak * (1 - TRAIL_CALLBACK_PCT / 100):
                orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                               'reason': f"[레인지] 트레일링 청산 (고점대비 -{TRAIL_CALLBACK_PCT:.0f}%, +{pr:.1f}%)",
                               'cooldown': 2, 'mark_partial': False})
                sold.add(code); continue

        entry_str = p.get('entry_date')
        if entry_str:
            try:
                if (today - datetime.strptime(entry_str, '%Y-%m-%d').date()).days >= TIMEOUT_DAYS:
                    orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                                   'reason': f"[레인지] 타임 스탑 ({TIMEOUT_DAYS}일 경과, {pr:+.1f}%)",
                                   'cooldown': 1, 'mark_partial': False})
                    sold.add(code); continue
            except ValueError:
                pass

    # 2. 진입: 넓은 채널 + 저점 근접 + 당일 급락 아님
    target_amount = view['nav'] * POSITION_WEIGHT
    held = len(portfolio) - len(sold)
    near_low_pcts = []  # 채널폭 통과 후보의 '저점 대비 %' — 진단용(아래 참고)
    for stock in candidates:
        if held >= MAX_HOLDINGS:
            break
        code = stock['code']
        if code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            continue
        price = float(stock.get('price', 0))
        amount = float(stock.get('amount', 0))
        if price <= 0 or amount < MIN_AMOUNT:
            continue
        ch = _channel(stock.get('range_history'))
        if not ch:
            continue
        low, high, width_pct = ch
        if width_pct >= MIN_WIDTH_PCT:
            near_low_pcts.append((code, (price / low - 1) * 100))
        daily_change = _parse_change_rate(stock)
        if (width_pct >= MIN_WIDTH_PCT
                and price <= low * (1 + LOW_ZONE)
                and daily_change > -2.0):
            qty = int(target_amount / price)
            if qty > 0:
                orders.append({'action': 'BUY', 'code': code, 'name': stock['name'], 'price': price,
                               'quantity': qty, 'cooldown': None,
                               'reason': f"[레인지] 저점 매수 (채널폭 {width_pct:.1f}%, 저점 {low:.0f})"})
                held += 1

    # 진단(2026-08-05): 진입 신호가 며칠째 안 나오는 게 '저점 근처인데 다른 조건에
    # 걸리는지' 아니면 '애초에 저점 근처 후보가 없는지' 로그가 없어 구분이 안 됐다.
    # 버즈(인기·상승 종목) 후보와 저점진입 조건이 구조적으로 안 맞을 가능성(Sim9-1과
    # 같은 패턴)을 확인하기 위한 최소 계측 — 매수가 없을 때만 한 줄 남긴다.
    if not any(o['action'] == 'BUY' for o in orders) and near_low_pcts:
        code, pct = min(near_low_pcts, key=lambda x: x[1])
        print(f"[레인지] 진입 없음 — 채널폭 통과 {len(near_low_pcts)}개 중 "
              f"저점에 가장 가까운 {code} 저점 대비 {pct:+.1f}% "
              f"(기준 +{LOW_ZONE * 100:.0f}% 이내)")
    return orders


class SidewaysSwingSimulator(BaseSimulator):
    """
    [Sim 5] 레인지 스윙형 (Range-Swing + Breakout Ride)
    ※ 클래스/상태파일명은 레거시('Sideways')를 유지하되 전략은 재정의됨.
       구 '추세 눌림목(+4% 고정익절)'은 목표가가 종목 실제 변동폭과 무관해 "이겨봐야 수수료"
       셋업까지 잡아 수수료에 알파가 잠식됨(2026-07 실측). 레인지 폭에 비례한 스윙으로 전환.
    - 진입: range_history(20일 종가) 채널 폭>=8% + 채널 저점 +3% 이내 + 당일 급락 아님.
            (좁은 채널은 수수료 대비 무의미 → 원천 스킵)
    - 청산: 하드손절 -3% / 트레일링(peak가 채널상단 근접 시 발동, 콜백 2%) / 7일 타임스탑.
            고정 익절 없음 → 상단 돌파 시 승자를 계속 라이딩.
    - 데이터: range_history는 5일 sparkline_price와 별개 필드(파리티 위해 양 환경 동일 채움).
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("Sideways", initial_cash)

    def get_universe(self):
        """KOSPI 시총 상위 100 — **중립** 유니버스.

        2026-08-14 실측으로 확정: 버즈 후보를 받는 동안 이 심은 매수가 0건이었다.

            [레인지] 진입 없음 — 채널폭 통과 19개 중
            저점에 가장 가까운 000660 저점 대비 +24.4% (기준 +3% 이내)

        채널폭은 18~19개가 통과하는데 저점에 가장 가까운 종목조차 +24%다.
        버즈 후보(인기·급등 종목)는 정의상 채널 저점 근처에 있을 수 없다 —
        "박스권 저점 매수"에 "지금 뜨는 종목" 풀을 물린 셈이었다.

        상승률/하락률 상위도 답이 아니다. 이 심은 "박스권 바닥에 **조용히**
        앉아 있는 종목"을 원하는데, 그건 오늘 오른 쪽에도 내린 쪽에도 없다.
        (하락률 상위는 `daily_change > -2.0` 게이트와도 정면 충돌한다.)

        조회 실패는 None이다 — 빈 리스트로 돌려주면 '후보가 없다'가 되어
        그날 이 심이 조용히 아무것도 안 한다. None이면 호출부가 파이프라인
        후보를 그대로 쓴다.

        채널(`range_history` 20일)은 `_enrich_universe`가 채운다 — 그 보강이
        없던 동안에는 자체 유니버스를 달면 오히려 진입이 **구조적으로
        불가능**해졌다(같은 날 고쳤다).
        """
        try:
            from src.data.market_cap_universe import fetch_top100
            return fetch_top100(limit=100)
        except Exception:
            return None

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        orders = decide_sideways(self._view(current_prices), candidates, current_prices)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
