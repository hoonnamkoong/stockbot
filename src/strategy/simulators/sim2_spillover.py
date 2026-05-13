from .base_simulator import BaseSimulator

class SectorSpilloverSimulator(BaseSimulator):
    """
    [Sim 2] 섹터 전이형 (Sector-Spillover)
    - 대장주 급등 후 아우(관련주)의 순환매 포착
    """
    SECTOR_MAP = {
        "반도체": {"leaders": ["005930", "000660"], "followers": ["041510", "005290", "067310"]},
        "이차전지": {"leaders": ["006400", "373220"], "followers": ["066970", "247540", "091990"]},
        "자동차": {"leaders": ["005380", "000270"], "followers": ["012330", "010120"]},
        "AI/소프트웨어": {"leaders": ["035420", "035720"], "followers": ["041190", "259960"]}
    }

    def __init__(self, initial_cash=5000000):
        super().__init__("Spillover", initial_cash)

    def _get_dynamic_sectors(self, candidates):
        """[V2] 동적 테마 그룹화 (키워드 기반)"""
        themes = {}
        for stock in candidates:
            # [V50.2] 키워드 필드 확인 및 타입 호환 처리
            keywords = stock.get('top_keywords', [])
            if not keywords or keywords == "Backup": continue
            
            # 리스트와 문자열 모두 대응
            if isinstance(keywords, list):
                primary_theme = keywords[0].strip()
            else:
                primary_theme = str(keywords).split(',')[0].strip()
            if primary_theme not in themes:
                themes[primary_theme] = []
            themes[primary_theme].append(stock)
        return themes

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        candidate_map = {s['code']: s for s in candidates}
        portfolio_codes = list(self.state['portfolio'].keys())
        sold_today = set()

        # 고점 갱신
        self.update_peak_prices(current_prices)

        # 1. 청산 로직 (트레일링 스탑)
        for code in portfolio_codes:
            current_price = current_prices.get(code, 0)
            if current_price <= 0: continue
            
            # [V2] 트레일링 스탑 체크
            if self.check_trailing_stop(code, current_price, activation_pct=5.0, callback_pct=3.0):
                self.sell(code, current_price, reason="[전이/V2] 트레일링 스탑 익절")
                sold_today.add(code)
                continue

            # [Fix] 하드 스탑로스(손절) 로직 추가 (기존에는 수익 전환 전 하락 시 평생 물려있음)
            p_item = self.state['portfolio'][code]
            avg_price = p_item.get('avg_price', 0)
            if avg_price > 0:
                profit_rate = (current_price - avg_price) / avg_price * 100
                if profit_rate <= -7.0:
                    self.sell(code, current_price, reason=f"[전이/V2] 하드 손절 (-7%)")
                    sold_today.add(code)

        # 2. 진입 로직 (동적 섹터 전이)
        if not self.state.get('market_index_healthy', True): return self.calculate_stats(current_prices)
        
        target_amount = self.initial_cash / 10
        dynamic_themes = self._get_dynamic_sectors(candidates)

        for theme, stocks in dynamic_themes.items():
            if len(stocks) < 2: continue # 아우가 없는 외로운 대장은 패스
            
            # [V60.0 Consensus] 리더 선정 정교화 (등락률 * 거래대금 가중치)
            def get_rs_score(s):
                chg = get_chg(s)
                amt = float(s.get('amount', 0)) / 1_000_000_000 # 10억 단위
                return chg * (amt ** 0.5) # 거래대금이 클수록 대장주 가중치

            sorted_stocks = sorted(stocks, key=get_rs_score, reverse=True)
            leader = sorted_stocks[0]
            leader_change = get_chg(leader)
            leader_tp = float(leader.get('tick_power', 100))
            
            if leader_change >= 3.0: # 대장주가 3% 이상 뿜어줄 때
                for follower in sorted_stocks[1:]:
                    f_code = follower['code']
                    if f_code in self.state['portfolio'] or f_code in sold_today: continue
                    
                    # [Fix] 유동성 필터: 거래대금 10억 미만 아우주 제외
                    amount = float(follower.get('amount', 0))
                    if amount < 1_000_000_000: continue

                    # [V60.0 Consensus] 호가창 전이 및 수급 확인
                    # 대장주의 수급(체결강도)이 강하고, 아우주의 매도호가 잔량이 줄어드는(bid_ask_ratio < 1.0) 시점
                    f_change = get_chg(follower)
                    f_bar = float(follower.get('bid_ask_ratio', 1.0))
                    
                    is_leader_strong = leader_change >= 3.0 and leader_tp >= 110.0
                    is_follower_ready = f_bar < 1.0 or self.validate_tick_power(follower, 110.0)

                    if is_leader_strong and is_follower_ready and (0.0 <= f_change < leader_change * 0.6):
                        price = float(follower.get('price', 0))
                        if price <= 0: continue
                        qty = int(target_amount / price)
                        if qty > 0:
                            self.buy(f_code, follower['name'], price, qty, 
                                     reason=f"[전이/V2] '{theme}' 테마 동적 포착 (Leader: {leader['name']} +{leader_change}%)")

        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
