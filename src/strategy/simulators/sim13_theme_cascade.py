from .base_simulator import BaseSimulator, get_kst_date

_parse_change_rate = BaseSimulator.parse_change_rate
_cooldown_active = BaseSimulator.cooldown_active
_period_change = BaseSimulator.calc_period_change
_adx = BaseSimulator.calculate_adx

# ── 파라미터 (2026-08-22 "3기법 믹스" 리서치 근거 — 대화 전체가 리서치 로그다) ──
# output/ohlcv_top100.csv(2026-03-05~07-29, 코스피100 100종목) 5분위 스프레드
# 테스트 + output/research/investor_flows.csv(2026-07-03~08-14, 394종목) 수급
# 정량검증 + 예비 체결 시뮬레이션(테마군 14종목, 32~43건) 결과를 그대로 옮겼다.
#
# 계층분리가 핵심이다 — 테마 주도군(삼성·SK·LG 14종목) 내부에서 ADX Q5-Q1=+6.61%p,
# MFI Q5-Q1=+9.93%p로 나머지 86종목(+2.03%p/+2.88%p)보다 3배 가까이 강했다.
# MFI는 실시간 후보 데이터에 거래량 일별 이력이 없어 이번 버전엔 못 넣었다 —
# ADX(추세강도)와 amount_ma20(거래대금서프라이즈)이 그 대역을 대신한다.
#
# ⚠ 인과적(룩어헤드 없는) 재검증에서 국면게이트의 승률 개선 효과는 크지 않았다
# (게이트없음 55.8%→인과적게이트 56.7%, 룩어헤드 버전의 71.9%는 사후정보 착시).
# 게이트는 유지하되 "승률을 크게 끌어올려준다"는 기대는 하지 않는다.
MAX_HOLDINGS = 6
POSITION_WEIGHT = 0.15           # NAV 대비 종목당 비중 (6종목×15%=최대 90%)
GROUP_CAP_RATIO = 0.5            # 동일 계열 합산 투입비중 상한(NAV 대비)

PERIOD_CHG_MIN = 15.0            # 1단 테마 프록시: range_history(~20거래일) 누적 변동률 하한.
                                  # 실시간 후보엔 3개월치 이력이 없어 가용 최장 구간으로 근사한다.
ADX_MIN = 40.0                   # 2단 이벤트탐지: 추세강도(ER 근사) 하한. Sim4-1과 같은 임계값.
AMOUNT_RATIO_MIN = 1.3           # 2단: 당일 거래대금 / 20일 평균(거래대금서프라이즈 근사)
PER_MAX = 40.0                   # 3단 밸류게이트: PER 상한(Sim12 PER_HIGH와 동일 임계 재사용).
                                  # 삼성전기 PER 97배가 모멘텀 1위였지만 이 게이트에 걸려
                                  # 탈락하는 사례가 설계의 계기였다(Part VII 시운전).

STOP_PCT = -5.0                  # 하드손절(예비 백테스트 파라미터 그대로)
MAX_HOLD_DAYS = 10               # 최대 보유일(설계서 "1~10거래일")

# 계열(그룹) 매핑 — 자동 섹터/지분 데이터가 없어(data/sector_per_pbr.json이 비어
# 있음을 확인했다) 실제 시운전에서 확인된 계열만 수동으로 얹는다. 다른 종목은
# 코드 자체를 그룹으로 취급해 사실상 cap이 걸리지 않는다. 완전한 자동 매핑은
# 다음 개선 과제다.
GROUP_MAP = {
    '005930': 'samsung', '005935': 'samsung', '032830': 'samsung', '028260': 'samsung',
    '000810': 'samsung', '006400': 'samsung', '018260': 'samsung',
    '000660': 'sk', '402340': 'sk', '034730': 'sk', '096770': 'sk',
    '066570': 'lg', '011070': 'lg', '051910': 'lg',
}


def _fn(funnel, code, reason, **vals):
    """왜 안 샀는지 한 줄 남긴다(심4-1·심6·심9·심12와 같은 방식)."""
    if funnel is None:
        return
    funnel.append({'code': code, 'reason': reason, **vals})


def _holding_days(p_item, today):
    s = p_item.get('entry_date', '')
    try:
        from datetime import datetime
        return (today - datetime.strptime(s, '%Y-%m-%d').date()).days if s else 0
    except Exception:
        return 0


def _group_of(code):
    return GROUP_MAP.get(code, code)


def _group_invested_ratio(group, portfolio, current_prices, nav):
    """이 그룹에 이미 투입된 비중(NAV 대비). NAV 조회 불가면 0(캡을 걸지 않음 — 모르는
    채로 진입을 막는 쪽보다는, 이미 다른 게이트를 통과한 종목이라 보수적으로 통과시킨다)."""
    if nav <= 0:
        return 0.0
    total = 0.0
    for c, item in portfolio.items():
        if _group_of(c) != group:
            continue
        px = current_prices.get(c) or item.get('avg_price', 0)
        total += item.get('quantity', 0) * px
    return total / nav


def decide_sim13(view, candidates, current_prices, regime, funnel=None):
    """[Sim13] 테마×모멘텀×밸류 계층분리형 이벤트 트레이딩. 순수 함수. Order 리스트 반환.

    설계 배경(2026-08-22 "최근 투자기법 종합 리서치" — 지표 카탈로그 → 기법 적합도
    검증 → 3기법 믹스 설계 → 국면/수급/체결 정량검증까지 이어진 대화 전체가 근거):
    - 1단(테마): range_history(~20거래일) 누적 변동률로 "이미 강하게 움직이는 종목"을
      근사 게이트로 쓴다. 진짜 3개월 그룹/섹터 클러스터링은 아니다 — 다음 개선 과제.
    - 2단(이벤트탐지): ADX(ER 근사) + 거래대금서프라이즈(amount/amount_ma20). 코스피100
      5개월 표본에서 테마군 내부 신호가 나머지보다 3배 가까이 강했다(본문 파라미터
      주석 참고). 외국인 20일 순매수 확인을 가점 조건으로 요구한다(수급 정량검증에서
      유일하게 방향이 뚜렷했던 신호, Q5-Q1=+1.19%p).
    - 3단(밸류): PER 상한으로 과열 추격을 거른다.
    - 국면게이트: BEAR·판정불가면 신규 진입 없음(청산은 계속). 다만 룩어헤드 없는
      재검증에서 승률 개선 효과는 미미했다 — 완전히 믿지 않는다.
    - 그룹집중상한: 시운전에서 최종 후보 8개 중 5개가 삼성 계열로 쏠렸던 문제의 방지책.

    페이퍼 관찰 단계(tradeable: false) — 예비 백테스트뿐(단일 5개월 구간, 32~43건),
    임계값은 전부 근사치다. Sim4-1과 신호(ADX) 일부가 겹치지만 유니버스·게이트
    구조가 달라 별개 후보로 다룬다(Sim4-1은 건드리지 않는다).
    """
    orders = []
    portfolio = view['portfolio']
    today = get_kst_date()
    sold = set()

    # 1. 청산: 하드손절 + 보유일 상한
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
                           'reason': f"[Sim13] 손절 ({pr:.1f}%)", 'cooldown': 2, 'mark_partial': False})
            sold.add(code)
            continue

        if _holding_days(p, today) >= MAX_HOLD_DAYS:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[Sim13] 보유기간 만료({MAX_HOLD_DAYS}일)", 'cooldown': 1, 'mark_partial': False})
            sold.add(code)
            continue

    # 2. 국면게이트: BULL/SIDEWAYS만 신규 진입. BEAR·판정불가는 청산만(위에서 이미 처리).
    if regime not in ('BULL', 'SIDEWAYS'):
        _fn(funnel, '_gate', 'regime_blocked', regime=regime)
        return orders

    held = len(portfolio) - len(sold)
    nav = view['nav']
    for stock in candidates:
        # 보유 상한도 **안 산 이유**다. 2026-09-01에 실전 심이 이 갈래를 기록하지
        # 않아 "후보 30 중 23만 설명되는" 로그가 나왔고, 그날 매매 0건의 원인을
        # 소급 추론해야 했다. 여기서 끊기면 뒤 후보는 평가조차 안 되므로,
        # 몇 개를 안 봤는지가 남아야 후보 수와 탈락 수의 합이 맞는다.
        if held >= MAX_HOLDINGS:
            _fn(funnel, '_gate', 'max_holdings', held=held)
            break
        code = stock['code']
        if code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            _fn(funnel, code, 'held_or_cooldown')
            continue

        price = float(stock.get('price', 0))
        if price <= 0:
            _fn(funnel, code, 'no_price')
            continue

        # 1단: 테마(모멘텀 프록시)
        range_history = stock.get('range_history', [])
        period_chg = _period_change(range_history) if range_history else None
        if not range_history or period_chg < PERIOD_CHG_MIN:
            _fn(funnel, code, 'theme_momentum_weak', period_chg=period_chg)
            continue

        # 2단: 이벤트탐지(추세강도 + 거래대금서프라이즈 + 외국인 수급)
        adx = _adx(range_history)
        if adx < ADX_MIN:
            _fn(funnel, code, 'adx_weak', adx=adx)
            continue

        amount = stock.get('amount')
        amount_ma20 = stock.get('amount_ma20')
        amount_ratio = (amount / amount_ma20) if (amount and amount_ma20) else None
        if amount_ratio is None or amount_ratio < AMOUNT_RATIO_MIN:
            _fn(funnel, code, 'amount_not_surprised', amount_ratio=amount_ratio)
            continue

        frgn_20d = stock.get('frgn_net_20d')
        if frgn_20d is None or frgn_20d <= 0:
            _fn(funnel, code, 'no_frgn_support', frgn_net_20d=frgn_20d)
            continue

        # 3단: 밸류게이트(과열 추격 방지)
        per = stock.get('per')
        if per is not None and per > 0 and per > PER_MAX:
            _fn(funnel, code, 'per_too_high', per=per)
            continue

        # 그룹집중상한
        group = _group_of(code)
        cur_ratio = _group_invested_ratio(group, portfolio, current_prices, nav)
        if cur_ratio + POSITION_WEIGHT > GROUP_CAP_RATIO:
            _fn(funnel, code, 'group_cap', group=group, cur_ratio=cur_ratio)
            continue

        invest = nav * POSITION_WEIGHT
        qty = int(invest / price)
        if qty <= 0:
            _fn(funnel, code, 'qty_zero', price=price)
            continue

        orders.append({
            'action': 'BUY', 'code': code, 'name': stock.get('name', code), 'price': price,
            'quantity': qty, 'cooldown': None,
            'reason': (f"[Sim13] 테마캐스케이드 진입 (기간 {period_chg:.1f}%, ADX {adx:.1f}, "
                       f"거래대금비 {amount_ratio:.2f}, 외인20일 {frgn_20d:+.1f}%, PER {per})"),
        })
        held += 1

    return orders


from ..regime_state import read_regime


class ThemeCascadeSimulator(BaseSimulator):
    """
    [Sim 13] 테마×모멘텀×밸류 계층분리 (Theme-Momentum-Value Cascade)
    - 2026-08-22 "최근 투자기법 종합 리서치"(코스피 지표 카탈로그 → 기법 적합도 검증
      → 3기법 믹스 설계 → 국면/수급/체결 정량검증) 기반.
    - 1단 테마(range_history 누적 변동률 근사) → 2단 이벤트탐지(ADX+거래대금서프라이즈
      +외국인 20일 순매수) → 3단 밸류게이트(PER 상한)의 3단 깔때기.
    - 국면게이트: BULL/SIDEWAYS만 신규진입, BEAR·판정불가는 청산만.
    - 그룹집중상한: 확인된 계열(삼성·SK·LG)만 수동 매핑, 합산 50% 초과 진입 금지.
    - 청산: 하드손절 -5%, 최대 보유 10거래일.
    - 페이퍼 관찰 단계(tradeable: false) — 백테스트는 예비 수준(단일 5개월 구간,
      32~43건), 실전 신뢰도 아님. Sim4-1과 신호 일부(ADX)가 겹치지만 유니버스와
      게이트 구조가 달라 별개 후보로 다룬다.
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("ThemeCascade", initial_cash)

    def get_universe(self):
        """코스피 등락률 상승률 상위 종목. 테마 후보군은 이미 오르고 있는 종목에서
        나온다는 전제라, Sim12와 달리 하락률 조회는 하지 않는다(60초 루프 예산
        절약 — Sim12 get_universe 주석의 예산 경고 참고)."""
        try:
            from src.trade.kis_data_provider import KISDataProvider
            kis = KISDataProvider()
            stocks = kis.get_fluctuation_rank(market='0001', sort='0', limit=40) or []
            return stocks or None
        except Exception:
            return None

    def _read_regime(self):
        """Sim0(리베로)의 국면 판단을 읽는다. 판단 불가면 None — 신규 진입을
        건너뛴다(Sim6·Sim12와 같은 원칙)."""
        return read_regime(self.data_dir)[0]

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        regime = self._read_regime()
        funnel = []
        orders = decide_sim13(self._view(current_prices), candidates, current_prices,
                              regime, funnel=funnel)
        self._log_funnel(candidates, funnel, orders, regime)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)

    @staticmethod
    def _log_funnel(candidates, funnel, orders, regime) -> None:
        """어느 국면에서 어느 게이트에 막혔는지 남긴다(sim_diag, 심6·심9·심12와 같은 방식)."""
        try:
            from collections import Counter
            if not funnel and not orders:
                return
            try:
                from src.data import sim_diag
                sim_diag.append('sim13', [dict(f, decision='skip') for f in funnel]
                                + [dict(code=o.get('code'), reason='entry', decision='entry')
                                   for o in orders], log=lambda *_: None)
            except Exception:
                pass
            c = Counter(f['reason'] for f in funnel)
            parts = ', '.join(f'{k} {v}' for k, v in c.most_common())
            buy_count = len([o for o in orders if o['action'] == 'BUY'])
            print(f"[Sim13 깔때기] 국면={regime} 후보 {len(candidates)} → 매수 {buy_count} | 탈락: {parts}")
        except Exception as e:
            print(f'[Sim13 깔때기] 기록 실패(무시): {e}')
