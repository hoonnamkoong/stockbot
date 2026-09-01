from .base_simulator import BaseSimulator, get_kst_date, DEFAULT_INITIAL_CASH

_parse_change_rate = BaseSimulator.parse_change_rate
_cooldown_active = BaseSimulator.cooldown_active
_period_change = BaseSimulator.calc_period_change

# ── 파라미터(2026-08-20 KOSPI 규칙마이닝 분위수 경계의 근사치 — 정밀 보정 아님) ──
MAX_HOLDINGS = 5
POSITION_WEIGHT = 0.19

# ⚠ amount_ratio(아래 두 게이트)는 리서치가 측정한 것과 시간 기준이 다르다 —
# 리서치는 EOD(하루 완결) 거래대금 대비 20일 평균이었는데, 실전 후보의 `amount`는
# KIS 등락률 순위가 주는 **조회 시점까지의 장중 누적** 거래대금이다(amount_ma20은
# 여전히 완결된 하루 평균). 그 결과 장 초반엔 이 비율이 구조적으로 낮게 잡혀
# avoid_amount_dry가 과도하게 걸리고, 플레이북2 진입은 하루 거래량이 상당히
# 소화된 뒤(대체로 오후)로 몰릴 수 있다 — 2026-08-21 최종 리뷰 지적. 관찰 기간 중
# sim12_diag_*.csv의 avoid_amount_dry/pb2_thin_liquidity 시간대별 비율을 봐서
# 시각 스케일링(세션 경과 비율로 나누기, 또는 전일 완결 거래대금으로 교체 등)이
# 필요한지 판단할 것 — 지금은 임계값을 건드리지 않는다(관찰 데이터 없이 추측하지
# 않는다).
AMOUNT_RATIO_DRY = 0.65          # 거래대금 급감(회피). 리서치 q1 상한 그대로.
AMOUNT_RATIO_OK = 1.0            # 플레이북2 최소 유동성. 리서치 quantile(0.6)≈1.01 근사.
PER_HIGH = 40.0                  # 고PER(회피 조합용). 리서치 q5 하한 44.6의 보수적 근사.
ORGN_NET_20D_SELL = -5.0         # 기관 20일 매도국면. 리서치 q1 상한 -5.94 근사.
FRGN_NET_20D_SELL = -5.0         # 외국인 20일 매도국면. 리서치 q1 상한 -5.79 근사.
FRGN_HOLD_CHG_5D_DROP = -1.0     # 외인 보유율 5일 급감. 표본이 작아 보수적으로 완화(원 규칙12는 더 좁음).

PERIOD_CHG_10D_BULL_MIN = 8.0    # 플레이북1: 10일간 이미 상승 중(모멘텀 확인).
DEV_MA20_BULL_MIN = 5.0          # 플레이북1: MA20 위로 뚜렷하게 이격.
PERIOD_CHG_5D_CRASH_MAX = -6.0   # 플레이북2: 5일 급락(하위20% 근사, q1 상한 -5.78).

RET_1D_HIGH = 5.0                # 회피(데드캣): 당일 급등 기준.
PERIOD_CHG_10D_CRASH_MAX = -10.0  # 회피(데드캣): 10일간 하락추세였는지.

STOP_PCT = -7.0                  # 하드손절. Sim2와 동일 관례.
TRAIL_ACTIVATION_PCT = 5.0       # 트레일링 활성화 수익률. Sim2와 동일 관례.
TRAIL_CALLBACK_PCT = 3.0         # 트레일링 콜백(고점 대비 하락률). Sim2와 동일 관례.
PLAYBOOK2_TIMESTOP_DAYS = 5       # 급락반등형 최대 보유일(설계서 "3~5일" 상한).


def _fn(funnel, code, reason, **vals):
    """왜 안 샀는지 한 줄 남긴다(심4-1·심6·심9와 같은 방식)."""
    if funnel is None:
        return
    funnel.append({'code': code, 'reason': reason, **vals})


def _holding_days(p_item, today):
    s = p_item.get('entry_date', '')
    try:
        return (today - date_fromiso(s)).days if s else 0
    except Exception:
        return 0


def date_fromiso(s):
    from datetime import datetime
    return datetime.strptime(s, '%Y-%m-%d').date()


def _pchg(range_history, days):
    """N거래일 전 종가 대비 변동률(%). 행이 부족하면 None(모른다 — 0%로 지어내지 않는다)."""
    if not range_history or len(range_history) < days + 1:
        return None
    return _period_change(range_history[-(days + 1):])


def _dev_ma(range_history, price, window):
    """가격이 최근 window일 평균(MA) 대비 몇 % 위/아래인지. 재료 부족하면 None."""
    if not range_history or len(range_history) < window or price <= 0:
        return None
    hist = range_history[-window:]
    ma = sum(hist) / len(hist)
    if ma <= 0:
        return None
    return (price - ma) / ma * 100.0


def _avoid(stock, funnel):
    """국면 무관 공통 회피 게이트. 걸리면 True(신규 진입 금지)."""
    code = stock['code']

    amount = stock.get('amount')
    amount_ma20 = stock.get('amount_ma20')
    amount_ratio = (amount / amount_ma20) if (amount and amount_ma20) else None
    if amount_ratio is not None and amount_ratio <= AMOUNT_RATIO_DRY:
        _fn(funnel, code, 'avoid_amount_dry', amount_ratio=amount_ratio)
        return True

    orgn_20d = stock.get('orgn_net_20d')
    per = stock.get('per')
    if (orgn_20d is not None and orgn_20d <= ORGN_NET_20D_SELL
            and per is not None and per >= PER_HIGH):
        _fn(funnel, code, 'avoid_orgn_sell_high_per', orgn_net_20d=orgn_20d, per=per)
        return True

    frgn_20d = stock.get('frgn_net_20d')
    if frgn_20d is not None and frgn_20d <= FRGN_NET_20D_SELL:
        _fn(funnel, code, 'avoid_frgn_sell_20d', frgn_net_20d=frgn_20d)
        return True

    frgn_hold_chg = stock.get('frgn_hold_chg_5d')
    if frgn_hold_chg is not None and frgn_hold_chg <= FRGN_HOLD_CHG_5D_DROP:
        _fn(funnel, code, 'avoid_frgn_hold_drop', frgn_hold_chg_5d=frgn_hold_chg)
        return True

    ret_1d = _parse_change_rate(stock)
    period_chg_10d = _pchg(stock.get('range_history', []), 10)
    if (ret_1d >= RET_1D_HIGH and period_chg_10d is not None
            and period_chg_10d <= PERIOD_CHG_10D_CRASH_MAX):
        _fn(funnel, code, 'avoid_deadcat', ret_1d=ret_1d, period_chg_10d=period_chg_10d)
        return True

    return False


def _playbook1_entry(stock, funnel):
    """모멘텀 지속형(BULL 전용). (통과여부, 사유문구)."""
    code = stock['code']
    price = float(stock.get('price', 0))
    range_history = stock.get('range_history', [])
    period_chg_10d = _pchg(range_history, 10)
    dev_ma20 = _dev_ma(range_history, price, 20)
    if period_chg_10d is None or dev_ma20 is None:
        _fn(funnel, code, 'pb1_no_history')
        return False, ''
    if period_chg_10d < PERIOD_CHG_10D_BULL_MIN:
        _fn(funnel, code, 'pb1_momentum_weak', period_chg_10d=period_chg_10d)
        return False, ''
    if dev_ma20 < DEV_MA20_BULL_MIN:
        _fn(funnel, code, 'pb1_below_ma20', dev_ma20=dev_ma20)
        return False, ''
    return True, f"[Sim12] 상승국면 모멘텀 지속 (10일 {period_chg_10d:+.1f}%, MA20이격 {dev_ma20:+.1f}%)"


def _playbook2_entry(stock, funnel):
    """급락반등형(SIDEWAYS/BEAR 전용). (통과여부, 사유문구)."""
    code = stock['code']
    range_history = stock.get('range_history', [])
    period_chg_5d = _pchg(range_history, 5)
    if period_chg_5d is None:
        _fn(funnel, code, 'pb2_no_history')
        return False, ''
    if period_chg_5d > PERIOD_CHG_5D_CRASH_MAX:
        _fn(funnel, code, 'pb2_not_crashed', period_chg_5d=period_chg_5d)
        return False, ''

    amount = stock.get('amount')
    amount_ma20 = stock.get('amount_ma20')
    amount_ratio = (amount / amount_ma20) if (amount and amount_ma20) else None
    if amount_ratio is None or amount_ratio < AMOUNT_RATIO_OK:
        _fn(funnel, code, 'pb2_thin_liquidity', amount_ratio=amount_ratio)
        return False, ''

    orgn_20d = stock.get('orgn_net_20d')
    if orgn_20d is None or orgn_20d <= 0:
        _fn(funnel, code, 'pb2_no_inst_buying', orgn_net_20d=orgn_20d)
        return False, ''

    return True, f"[Sim12] 급락반등 (5일 {period_chg_5d:.1f}%, 기관20일 {orgn_20d:+.1f}%)"


def decide_sim12(view, candidates, current_prices, regime, funnel=None):
    """[Sim12] 국면이원(모멘텀 지속형/급락반등형) 결정. 순수 함수. Order 리스트 반환.

    BULL이면 플레이북1(이미 오르는 종목 순추세), SIDEWAYS/BEAR면 플레이북2(5일 급락
    + 거래대금 유지 + 기관 20일 순매수)로 진입 로직 자체가 바뀐다 — 2026-08-20 KOSPI
    규칙마이닝 "최고수익 종목 프로파일" 절 실측(강세장 4월 vs 약세~횡보 7~8월에서
    최고수익 패턴이 정반대였다)을 그대로 반영.
    """
    orders = []
    portfolio = view['portfolio']
    today = get_kst_date()
    sold = set()

    # 1. 청산: 하드손절(공통) + 플레이북2 전용 5일 타임스탑.
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
                           'reason': f"[Sim12] 하드 손절 ({pr:.1f}%)", 'cooldown': 2, 'mark_partial': False})
            sold.add(code)
            continue

        if p.get('playbook') == 2 and _holding_days(p, today) >= PLAYBOOK2_TIMESTOP_DAYS:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': "[Sim12] 급락반등 타임스탑(5일)", 'cooldown': 1, 'mark_partial': False})
            sold.add(code)
            continue

        # 트레일링 스탑: 수익이 한 번이라도 TRAIL_ACTIVATION_PCT를 찍었고 고점 대비
        # TRAIL_CALLBACK_PCT 하락하면 매도. self.check_trailing_stop과 같은 계산이지만
        # decide_sim12는 순수함수라 상태 메서드를 못 부른다 — 심6과 같은 방식으로
        # portfolio에 이미 있는 peak_price를 직접 계산에 쓴다(run()이 decide 호출 전에
        # update_peak_prices를 먼저 불러 최신 고점을 보장한다).
        peak = p.get('peak_price', avg)
        drop_from_peak = (peak - cur) / peak * 100 if peak > 0 else 0
        activated = pr >= TRAIL_ACTIVATION_PCT or peak > avg * (1 + TRAIL_ACTIVATION_PCT / 100)
        if activated and drop_from_peak >= TRAIL_CALLBACK_PCT:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[Sim12] 트레일링 스탑 (고점대비 -{drop_from_peak:.1f}%)",
                           'cooldown': 2, 'mark_partial': False})
            sold.add(code)
            continue

    # 2. 진입: 국면 판정불가면 신규 진입 없음(청산은 위에서 이미 처리했다).
    if regime not in ('BULL', 'SIDEWAYS', 'BEAR'):
        return orders

    held = len(portfolio) - len(sold)
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

        if _avoid(stock, funnel):
            continue

        price = float(stock.get('price', 0))
        if price <= 0:
            _fn(funnel, code, 'no_price')
            continue

        if regime == 'BULL':
            ok, reason = _playbook1_entry(stock, funnel)
            playbook = 1
        else:
            ok, reason = _playbook2_entry(stock, funnel)
            playbook = 2
        if not ok:
            continue

        invest = view['nav'] * POSITION_WEIGHT
        qty = int(invest / price)
        if qty <= 0:
            _fn(funnel, code, 'qty_zero', price=price)
            continue

        orders.append({'action': 'BUY', 'code': code, 'name': stock.get('name', code), 'price': price,
                       'quantity': qty, 'cooldown': None, 'playbook': playbook, 'reason': reason})
        held += 1

    return orders


from ..regime_state import read_regime


class RegimeDualSimulator(BaseSimulator):
    """
    [Sim 12] 국면이원 반등/추세형 (Regime-Dual Momentum/Rebound)
    - 2026-08-20 KOSPI 규칙마이닝(Tier1) 기반. Sim0(리베로) 국면에 따라 진입 로직
      자체가 바뀐다.
    - BULL: 플레이북1(모멘텀 지속형) — 10일간 이미 강하게 상승 + MA20 위로 크게 이격.
    - SIDEWAYS/BEAR: 플레이북2(급락반등형) — 5일 급락 + 거래대금 유지 + 기관 20일
      순매수.
    - 공통 회피 게이트: 거래대금 급감/기관·외국인 20일 지속 순매도/외인 보유율
      급감/데드캣(당일급등+10일 하락추세)은 국면 무관하게 신규 진입 금지.
    - 청산: 하드손절 -7% + 트레일링(+5% 활성/-3% 콜백, 둘 다 공통·Sim2와 동일 관례).
      플레이북2는 추가로 5일 타임스탑(반등이 10일 시계에서 재하락하는 경향 — 설계서
      참고). 플레이북1은 타임스탑 없음(추세를 더 태운다).
    - 페이퍼 관찰 단계(tradeable: false) — 백테스트 미검증, 임계값은 리서치 분위수
      경계의 근사치다.
    """
    def __init__(self, initial_cash=DEFAULT_INITIAL_CASH):
        super().__init__("RegimeDual", initial_cash)

    def get_universe(self):
        """코스피 등락률 상승률·하락률 각 30개를 합친다. 상승률만 보면 플레이북2
        (급락반등형)의 후보가 원천적으로 안 잡힌다 — 두 플레이북이 정반대 방향의
        종목을 필요로 하므로 양쪽 다 확보해야 한다.

        ⚠ 하락률(sort='1') 조회는 이 심이 처음 쓴다 — 다른 매매 심은 전부 상승률만
        본다. 상승률 30은 다른 심과 겹쳐 공유 보강 풀에서 사실상 공짜지만, 하락률
        30종목은 이 심 때문에 순증되는 조회량이다. 60초 매매 루프의 예산은
        빡빡하다(trade_loop.py LOOP_BUDGET_SEC=85초, 이 루프가 도는 모든 심이 같은
        예산을 나눠 쓴다) — 2026-08-19에 다른 심(Sim10)이 예산을 넘겨 사이클
        하나를 통째로 날린 전례가 있다. 배포 후 첫 사이클들의 실측 소요시간을
        반드시 확인할 것 — 2026-08-21 최종 리뷰 지적. 초과하면 limit을 낮추거나
        BULL 국면에서는 하락률 조회를 건너뛰는 완화가 필요하다(지금은 측정 없이
        선제적으로 바꾸지 않는다).
        """
        try:
            from src.trade.kis_data_provider import KISDataProvider
            kis = KISDataProvider()
        except Exception:
            return None
        merged: dict = {}
        # 두 호출을 따로 감싼다 — 한쪽이 실패해도 이미 받은 반대쪽까지 버리지 않는다.
        try:
            for s in (kis.get_fluctuation_rank(market='0001', sort='0', limit=30) or []):
                merged[s['code']] = s
        except Exception:
            pass
        try:
            for s in (kis.get_fluctuation_rank(market='0001', sort='1', limit=30) or []):
                merged.setdefault(s['code'], s)
        except Exception:
            pass
        return list(merged.values()) or None

    def _read_regime(self):
        """Sim0(리베로)의 국면 판단을 읽는다. 판단 불가면 None — 신규 진입을
        건너뛴다(Sim6과 같은 원칙: 모르는 국면으로 실제 주문을 내지 않는다)."""
        return read_regime(self.data_dir)[0]

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        regime = self._read_regime()
        funnel = []
        orders = decide_sim12(self._view(current_prices), candidates, current_prices,
                              regime, funnel=funnel)
        self._log_funnel(candidates, funnel, orders, regime)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)

    @staticmethod
    def _log_funnel(candidates, funnel, orders, regime) -> None:
        """어느 국면에서 어느 게이트에 막혔는지 남긴다 — 심6·심9와 같은 방식
        (sim_diag)으로 db-data에 남아야 다음 사이클 이후에도 확인 가능하다."""
        try:
            from collections import Counter
            if not funnel and not orders:
                return
            try:
                from src.data import sim_diag
                sim_diag.append('sim12', [dict(f, decision='skip') for f in funnel]
                                + [dict(code=o.get('code'), reason='entry', decision='entry')
                                   for o in orders], log=lambda *_: None)
            except Exception:
                pass
            c = Counter(f['reason'] for f in funnel)
            parts = ', '.join(f'{k} {v}' for k, v in c.most_common())
            buy_count = len([o for o in orders if o['action'] == 'BUY'])
            print(f"[Sim12 깔때기] 국면={regime} 후보 {len(candidates)} → 매수 {buy_count} | 탈락: {parts}")
        except Exception as e:
            print(f'[Sim12 깔때기] 기록 실패(무시): {e}')
