from datetime import date

from .base_simulator import BaseSimulator, get_kst_date



def _fn(funnel, code, reason, **vals):
    """왜 안 샀는지 한 줄 남긴다(심5·심9와 같은 방식).

    2026-08-13 심 전체 감사: 심3은 8월 매수가 1건뿐인데 이유가 로그에 없었다.
    의심은 유니버스와 진입 조건이 서로 밀어낸다는 것이다 — 유니버스는
    get_finance_ratio_rank(ROE 수익성 상위)인데 진입은 '섹터 평균 대비 20%
    저평가'를 요구한다. 고ROE는 대개 고PER/PBR이라 둘이 반대 방향이다.
    거기에 거래대금 50억(전 심 최고 문턱)이 겹친다.

    추측으로 유니버스를 바꾸지 않고 먼저 센다. `not_cheap`이 후보 전량이면
    유니버스-조건 미스매치가 확정되고, `amount`가 전량이면 유동성 문턱이
    원인이다.
    """
    if funnel is None:
        return
    funnel.append({'code': code, 'reason': reason, **vals})

class SmartRiskSimulator(BaseSimulator):
    """
    [Sim 3] 가치 페어 전략 (Value Pair)
    - 업종 평균 대비 PER/PBR 20% 이하 저평가 + ADX 20 이상 추세 전환 종목 진입
    - Sim4(모멘텀)와 음의 상관 목표: 모멘텀 장에서 기회 적음, 조정/가치 장에서 기회 증가
    - 청산: +8% 익절 / -5% 손절 / 7일 타임스탑
    """
    MAX_HOLDINGS = 5
    POSITION_WEIGHT = 0.19  # 종목당 NAV 대비 비중 (0.19 × 5 = 최대 95% 투입)

    def __init__(self, initial_cash=3000000):
        super().__init__("Risk", initial_cash)

    def get_universe(self):
        """코스피 재무비율 수익성 상위 30개 종목 (FHPST01750000)."""
        try:
            from src.trade.kis_data_provider import KISDataProvider
            return KISDataProvider().get_finance_ratio_rank(market='0001', limit=30)
        except Exception:
            return None

    def _ttm_valuation(self, code, price):
        """TTM PER/PBR. 조회가 실패하면 빈 dict — 0으로 채워 '싸다'로 오판하지 않는다."""
        try:
            from src.trade.kis_data_provider import KISDataProvider
            return KISDataProvider().get_ttm_valuation(code, price)
        except Exception:
            return {}

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        candidate_map = {s['code']: s for s in candidates}
        portfolio_codes = list(self.state['portfolio'].keys())
        sold_today = set()

        self.update_peak_prices(current_prices)

        # 1. 청산
        for code in portfolio_codes:
            p_item = self.state['portfolio'][code]
            current_price = current_prices.get(code, 0)
            if current_price <= 0: continue

            avg_price = p_item.get('avg_price', 0)
            if avg_price <= 0: continue
            profit_rate = (current_price - avg_price) / avg_price * 100

            # 목표 익절 +8%
            if profit_rate >= 8.0:
                self.sell(code, current_price, reason=f"[가치페어] 목표 익절 ({profit_rate:.1f}%)")
                self.add_cooldown(code, 2)
                sold_today.add(code)
                continue

            # 손절 -5%
            if profit_rate <= -5.0:
                self.sell(code, current_price, reason=f"[가치페어] 손절 ({profit_rate:.1f}%)")
                self.add_cooldown(code, 3)
                sold_today.add(code)
                continue

            # 타임스탑: 7일 (≈5 영업일)
            entry_date_str = p_item.get('entry_date', '')
            if entry_date_str:
                try:
                    entry_date = date.fromisoformat(entry_date_str)
                    if (get_kst_date() - entry_date).days >= 7:
                        self.sell(code, current_price,
                                  reason=f"[가치페어] 타임스탑 ({(get_kst_date() - entry_date).days}일 보유)")
                        self.add_cooldown(code, 1)
                        sold_today.add(code)
                        continue
                except Exception as e:
                    # 2026-08-13 감사: 여기가 `date` 미import로 NameError를 내고
                    # 있었고, 이 except가 그걸 삼켜 **타임스탑이 배포 이래 한 번도
                    # 발동하지 않았다.** 조용한 실패는 없는 기능과 같다.
                    print(f'[Sim3] 타임스탑 판정 실패 {code}({entry_date_str}): {e}')

        # 2. 진입
        if len(self.state['portfolio']) >= self.MAX_HOLDINGS:
            return self.calculate_stats(current_prices)

        from src.data.sector_cache import SectorCache
        sector_cache = SectorCache()
        funnel = []
        target_amount = self.calc_nav(current_prices) * self.POSITION_WEIGHT

        for stock in candidates:
            if len(self.state['portfolio']) >= self.MAX_HOLDINGS: break
            code = stock['code']
            if code in self.state['portfolio'] or code in sold_today: continue
            if self.is_in_cooldown(code): continue

            price = float(stock.get('price', 0))
            amount = float(stock.get('amount', 0))
            if price <= 0: _fn(funnel, code, 'no_price'); continue
            if amount < 5_000_000_000: _fn(funnel, code, 'amount', amount=amount); continue  # 50억 유동성

            # PER/PBR은 **TTM 기준**으로 다시 계산한다.
            # KIS `inquire-price`의 per/pbr은 직전 **연간 결산** EPS·BPS 기준이라
            # 실적이 개선된 종목을 비싸게 보이게 한다(2026-08-17 실측: 삼성전자
            # 41.82 vs TTM 22.19, SK하이닉스 27.90 vs 15.89). 섹터 평균(sector_cache)은
            # 외부 통계라 TTM 기준인데 종목만 연간 기준이면, **실적 개선주는 비싸 보여
            # 걸러지고 정체주가 싸 보여 뽑힌다** — 저평가 필터가 정확히 반대로 작동한다.
            # 계산 실패는 0으로 남긴다(그 축은 판정에서 빠진다). 폴백으로 연간 값을
            # 쓰면 편향이 그대로 돌아온다.
            # 후보에 이미 TTM 값이 실려 있으면 그걸 쓴다(조회 절약·테스트 주입).
            if stock.get('per_ttm') or stock.get('pbr_ttm'):
                stock_per = float(stock.get('per_ttm') or 0)
                stock_pbr = float(stock.get('pbr_ttm') or 0)
            else:
                val = self._ttm_valuation(code, price)
                stock_per = val.get('per_ttm', 0.0)
                stock_pbr = val.get('pbr_ttm', 0.0)
            if stock_per <= 0 and stock_pbr <= 0: _fn(funnel, code, 'no_ttm_val'); continue

            # 업종 평균 조회
            sector_name = stock.get('sector_name', '')
            sector_avg = sector_cache.get_sector_avg(sector_name) if sector_name else None
            if not sector_avg: _fn(funnel, code, 'no_sector', sector=sector_name); continue

            # 업종 평균 대비 20% 이하 저평가 여부
            avg_per = sector_avg['avg_per']
            avg_pbr = sector_avg['avg_pbr']
            per_cheap = (0 < stock_per <= avg_per * 0.8)
            pbr_cheap = (0 < stock_pbr <= avg_pbr * 0.8)
            if not (per_cheap or pbr_cheap):
                _fn(funnel, code, 'not_cheap', per=stock_per, avg_per=avg_per,
                    pbr=stock_pbr, avg_pbr=avg_pbr, sector=sector_name)
                continue

            # ADX >= 20 (추세 전환 확인)
            sparkline = stock.get('sparkline_price', [])
            adx = self.calculate_adx(sparkline) if sparkline else 0.0
            if adx < 20.0: _fn(funnel, code, 'adx', adx=adx); continue

            # 오늘 종가 > 5일 전 종가 (가격 반등 확인)
            if len(sparkline) >= 6 and sparkline[-1] <= sparkline[-6]:
                _fn(funnel, code, 'no_rebound'); continue

            qty = int(target_amount / price)
            if qty > 0:
                reason = (
                    f"[가치페어] 업종 저평가 진입(TTM) "
                    f"(PER {stock_per:.1f}x / 섹터 {avg_per:.1f}x, "
                    f"PBR {stock_pbr:.2f}x / 섹터 {avg_pbr:.2f}x, "
                    f"ADX {adx:.1f}, 섹터: {sector_name})"
                )
                self.buy(code, stock['name'], price, qty, reason=reason)

        self._log_funnel(candidates, funnel)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)

    @staticmethod
    def _log_funnel(candidates, funnel) -> None:
        """게이트별 탈락 분포를 한 줄로. 진단이 심을 죽이면 안 되니 통째로 삼킨다."""
        try:
            from collections import Counter
            if not funnel:
                return
            c = Counter(f['reason'] for f in funnel)
            parts = ', '.join(f'{k} {v}' for k, v in c.most_common())
            print(f"[Sim3 깔때기] 후보 {len(candidates)} | 탈락: {parts}")
            # 저평가에서 걸린 종목은 실제 배수까지 남긴다 — 유니버스(고ROE)와
            # 조건(저평가)이 반대 방향인지 판단할 근거다.
            for f in [x for x in funnel if x['reason'] == 'not_cheap'][:3]:
                print(f"   저평가탈락 {f['code']}({f.get('sector', '')}): "
                      f"PER {f.get('per', 0):.1f}/{f.get('avg_per', 0):.1f} "
                      f"PBR {f.get('pbr', 0):.2f}/{f.get('avg_pbr', 0):.2f}")
        except Exception as e:
            print(f'[Sim3 깔때기] 기록 실패(무시): {e}')
