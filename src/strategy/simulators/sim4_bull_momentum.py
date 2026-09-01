from .base_simulator import BaseSimulator, DEFAULT_INITIAL_CASH, log_funnel



def _fn(funnel, code, reason, **vals):
    """왜 안 샀는지 한 줄 남긴다(전 심 공통 방식).

    심4는 진입 조건 다섯(기간모멘텀·당일상승·ADX·체결강도·수급)이 한 `if`에
    묶여 있어, 0건일 때 어느 축이 막았는지 밖에서 알 수 없었다. 심4-1이 같은
    형태로 하루 종일 침묵했던 적이 있고 그때도 조건을 쪼개서야 답을 찾았다.
    """
    if funnel is None:
        return
    funnel.append({'code': code, 'reason': reason, **vals})

class BullMomentumSimulator(BaseSimulator):
    """
    [Sim 4] 상승장 주도주 탑승형 (Bull-Momentum)
    - 고유동성 + 강한 기간 모멘텀 종목에 진입해 불타기로 비중 확대.
    - 고정 익절 없음: 트레일링 스탑으로만 청산하여 상승을 끝까지 라이딩.
    """
    MAX_HOLDINGS = 5
    POSITION_WEIGHT = 0.19  # 종목당 NAV 대비 비중 (0.19 × 5 = 최대 95% 투입)
    # ADX 상한(2026-08-05, 심4+4-1 합산 26건 실거래 재집계로 확정):
    # [0,40)→승률88.9%/+11.22%, [40,60)→100%/+13.46%, [60,80)→50%/-2.63%, [80,100]→28.6%/-6.25%.
    # 60을 기점으로 승률·평균ROI가 뒤집힌다 — 추세가 이미 다 나온(과열) 종목을 진입시켜
    # 반전에 물리는 패턴으로 해석. 구간당 4~9건이라 정밀한 임계값까진 못 정해 구간 경계인
    # 60을 그대로 쓴다.
    ADX_MAX = 60.0

    def __init__(self, initial_cash=DEFAULT_INITIAL_CASH):
        super().__init__("Bull", initial_cash)

    def get_universe(self):
        """코스피 당일 상승률 상위 30개 종목 (등락률 순위 FHPST01700000)."""
        try:
            from src.trade.kis_data_provider import KISDataProvider
            return KISDataProvider().get_fluctuation_rank(market='0001', sort='0', limit=30)
        except Exception:
            return None

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        candidate_map = {s['code']: s for s in candidates}
        portfolio_codes = list(self.state['portfolio'].keys())
        sold_today = set()

        self.update_peak_prices(current_prices)

        # 1. 청산 (트레일링 5/5 + ATR 3배 하드 손절, 고정 익절 없음)
        for code in portfolio_codes:
            p_item = self.state['portfolio'][code]
            stock = candidate_map.get(code)
            current_price = current_prices.get(code, 0)
            if current_price <= 0: continue
            avg_price = p_item.get('avg_price', 0)
            if avg_price <= 0: continue
            profit_rate = (current_price - avg_price) / avg_price * 100

            # 트레일링 스탑 (5% 활성화 후 고점 대비 5% 콜백) — 넓은 밴드로 잔파도 방어
            if self.check_trailing_stop(code, current_price, activation_pct=5.0, callback_pct=5.0):
                self.sell(code, current_price, reason="[상승모멘텀] 트레일링 스탑 익절 (라이딩 종료)")
                self.add_cooldown(code, 2)
                sold_today.add(code)
                continue

            # ATR 3배 하드 손절
            sparkline = stock.get('sparkline_price', []) if stock else []
            if sparkline and len(sparkline) >= 2:
                atr = self.calculate_atr(sparkline)
                atr_pct = (atr / avg_price) * 100 if avg_price > 0 else 3.0
            else:
                atr_pct = 3.0  # sparkline 부재 시 기본 3% (→ -9% 손절)
            if profit_rate <= -(3.0 * atr_pct):
                self.sell(code, current_price, reason=f"[상승모멘텀] ATR 3배 손절 ({profit_rate:.1f}%)")
                self.add_cooldown(code, 3)
                sold_today.add(code)
                continue

        # 2. 불타기 (Pyramiding) — 보유 종목 +5% & 미증액 시 1회만
        # is_scaled_out(base)는 부분매도 플래그와 충돌하므로 sim4 전용 'pyramided' 플래그 사용
        # 불타기도 매수다 — 왜 안 했는지가 남아야 한다. 진입 깔때기와 **장부를
        # 나눈다**: 두 판단은 모집단이 다르다(보유 종목 vs 후보). 한 장부에
        # 섞으면 "후보 = 매수 + 탈락" 회계가 깨져 미설명 경고가 무의미해진다.
        pyr = []
        pyr_bought = 0
        for code in list(self.state['portfolio'].keys()):
            if code in sold_today:
                _fn(pyr, code, 'sold_today')
                continue
            p_item = self.state['portfolio'][code]
            current_price = current_prices.get(code, 0)
            if current_price <= 0:
                _fn(pyr, code, 'no_price')
                continue
            avg_price = p_item.get('avg_price', 0)
            if avg_price <= 0:
                _fn(pyr, code, 'no_avg_price')
                continue
            profit_rate = (current_price - avg_price) / avg_price * 100
            # 불타기 추가 조건: 기관 OR 외인 추정 순매수 양수여야 허수 신호 제거
            _s = candidate_map.get(code, {})
            orgn_support = _s.get('orgn_fake_ntby_qty', 0)
            frgn_support = _s.get('frgn_fake_ntby_qty', 0)
            has_inst_support = (orgn_support > 0 or frgn_support > 0)
            if profit_rate < 5.0:
                _fn(pyr, code, 'profit_low', profit=profit_rate)
                continue
            if p_item.get('pyramided', False):
                _fn(pyr, code, 'already_pyramided')
                continue
            if not has_inst_support:
                _fn(pyr, code, 'no_inst', orgn=orgn_support, frgn=frgn_support)
                continue
            add_qty = int(p_item['quantity'] * 0.5)
            cost = add_qty * current_price
            if add_qty <= 0:
                _fn(pyr, code, 'qty_zero', held=p_item['quantity'])
                continue
            if cost > self.state['cash'] * 0.15:
                _fn(pyr, code, 'over_cash_cap', cost=cost, cash=self.state['cash'])
                continue
            if self.buy(code, p_item['name'], current_price, add_qty,
                        reason=f"[상승모멘텀] 불타기 50% (기관{orgn_support:+,}/외인{frgn_support:+,})"):
                pyr_bought += 1
                self.state['portfolio'][code]['pyramided'] = True
                self.save_state(current_prices)
            else:
                _fn(pyr, code, 'insufficient_cash',
                    need=cost, cash=self.state.get('cash', 0))

        # 보유 종목이 모집단이므로 candidates가 아니라 보유 목록을 넘긴다.
        log_funnel('불타기', list(self.state['portfolio'].keys()), pyr, buys=pyr_bought)

        # 3. 진입 (고유동성 + 강한 기간 모멘텀 + 당일 상승 + ADX + 체결강도)
        target_amount = self.calc_nav(current_prices) * self.POSITION_WEIGHT
        # 런당 한 번만 판정한다(종목마다 재계산하면 같은 답을 후보 수만큼 다시 낸다).
        tick_outage = self.tick_power_outage(candidates)
        funnel = []
        bought = 0
        for stock in candidates:
            code = stock['code']
            if len(self.state['portfolio']) >= self.MAX_HOLDINGS:
                _fn(funnel, code, 'max_holdings', held=len(self.state['portfolio']))
                break
            if code in self.state['portfolio'] or code in sold_today:
                _fn(funnel, code, 'held_or_sold_today')
                continue
            if self.is_in_cooldown(code):
                _fn(funnel, code, 'cooldown')
                continue

            # 필드 부재와 값 미달을 가른다 — `get(k, 0)`이면 키 없음이
            # "거래대금 0원"이 되어 유동성 미달로 잘못 읽힌다.
            raw_price, raw_amount = stock.get('price'), stock.get('amount')
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
            if amount < 3_000_000_000:  # 30억 고유동성
                _fn(funnel, code, 'amount', amount=amount)
                continue

            sparkline = stock.get('sparkline_price', [])
            adx = self.calculate_adx(sparkline) if sparkline else 0.0
            if adx < 15.0:
                _fn(funnel, code, 'adx_low', adx=adx)  # 슬립 모드
                continue
            if adx >= self.ADX_MAX:
                _fn(funnel, code, 'adx_high', adx=adx)  # 과열 모드
                continue

            period_change = self.calc_period_change(sparkline)
            daily_change = self.parse_change_rate(stock)

            orgn = stock.get('orgn_fake_ntby_qty', 0)
            frgn = stock.get('frgn_fake_ntby_qty', 0)
            has_inst = (orgn > 0 or frgn > 0)
            # 다섯 조건을 한 `if`로 묶으면 "안 샀다"만 남는다. 어느 축이
            # 막았는지가 곧 그날의 답이다.
            if not (5.0 <= period_change <= 40.0):
                _fn(funnel, code, 'period', period=period_change)
                continue
            if daily_change <= 0:
                _fn(funnel, code, 'daily_not_up', change=daily_change)
                continue
            if adx < 20.0:
                _fn(funnel, code, 'adx_entry_low', adx=adx)
                continue
            if not self.validate_tick_power(stock, threshold=120.0, outage=tick_outage):
                _fn(funnel, code, 'tick', tick=stock.get('tick_power'))
                continue
            if not has_inst:
                _fn(funnel, code, 'no_inst', orgn=orgn, frgn=frgn)
                continue
            qty = int(target_amount / price)
            if qty <= 0:
                _fn(funnel, code, 'qty_zero', price=price, target=target_amount)
                continue
            if self.buy(code, stock['name'], price, qty,
                        reason=f"[상승모멘텀] 주도주 탑승 (기간 {period_change:.1f}%, ADX {adx:.1f}, 기관{orgn:+,}/외인{frgn:+,})"):
                bought += 1
            else:
                _fn(funnel, code, 'insufficient_cash',
                    need=qty * price, cash=self.state.get('cash', 0))

        log_funnel('상승모멘텀', candidates, funnel, buys=bought)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
