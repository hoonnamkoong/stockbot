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
            # 키워드 필드 확인
            keywords = stock.get('top_keywords', '')
            if not keywords or keywords == "Backup": continue
            
            # 첫 번째 키워드를 대표 테마로 설정
            primary_theme = keywords.split(',')[0].strip()
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

        # 2. 진입 로직 (동적 섹터 전이)
        if not self.state.get('market_index_healthy', True): return self.calculate_stats(current_prices)
        
        target_amount = self.initial_cash / 10
        dynamic_themes = self._get_dynamic_sectors(candidates)

        for theme, stocks in dynamic_themes.items():
            if len(stocks) < 2: continue # 아우가 없는 외로운 대장은 패스
            
            # 리더 선정 (당일 등락률 가장 높은 종목)
            def get_chg(s):
                v = s.get('change_rate', s.get('daily_change_rate', 0))
                if isinstance(v, str): v = float(v.replace('%','').replace('+',''))
                return v

            sorted_stocks = sorted(stocks, key=get_chg, reverse=True)
            leader = sorted_stocks[0]
            leader_change = get_chg(leader)
            
            if leader_change >= 3.0: # 대장주가 3% 이상 뿜어줄 때
                for follower in sorted_stocks[1:]:
                    f_code = follower['code']
                    if f_code in self.state['portfolio'] or f_code in sold_today: continue
                    
                    f_change = get_chg(follower)
                    
                    # [V2] 갭 보정: 대장주의 60% 이하이거나 3% 미만이면 진입
                    if f_change < 3.0 or f_change < (leader_change * 0.6):
                        price = float(follower.get('price', 0))
                        if price <= 0: continue
                        qty = int(target_amount / price)
                        if qty > 0:
                            self.buy(f_code, follower['name'], price, qty, 
                                     reason=f"[전이/V2] '{theme}' 테마 동적 포착 (Leader: {leader['name']} +{leader_change}%)")

        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
