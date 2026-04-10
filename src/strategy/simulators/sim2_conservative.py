from .base_simulator import BaseSimulator
from datetime import datetime

class ConservativeSimulator(BaseSimulator):
    """
    [Sim 2] 보수적 방어형 (Conservative - Trailing Stop & Time Cut)
    - 3M 초기화 후 개시
    - Time Cut: T+3 종가 강제 청산
    - Hard Stop: -3%
    - Trailing Stop: 수익 +5% 돌파 후 고점 대비 -2% 하락 시 익절
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("Conservative", initial_cash) # 파일명: sim_conservative_state.json

    def run(self, candidates):
        """
        [Conservative] 통합 인터페이스
        """
        candidate_map = {s['code']: s for s in candidates}
        portfolio_codes = list(self.state['portfolio'].keys())
        today = datetime.now()

        # 1. 청산 및 트래킹 로직
        for code in portfolio_codes:
            p_item = self.state['portfolio'][code]
            stock = candidate_map.get(code)
            
            # 현재가 확보 (candidates에 없으면 평단가 활용)
            current_price = stock.get('price', stock.get('현재가', p_item['avg_price'])) if stock else p_item['avg_price']
            if current_price <= 0: continue
            
            # 고점 갱신
            self.update_peak_price(code, current_price)
            
            # 수익률 계산
            profit_rate = (current_price - p_item['avg_price']) / p_item['avg_price'] * 100
            peak_price = p_item.get('peak_price', current_price)
            drop_from_peak = (peak_price - current_price) / peak_price * 100
            
            # --- 청산 조건 검사 ---
            
            # (1) Hard Stop: -3%
            if profit_rate <= -3.0:
                self.sell(code, current_price, reason=f"[보수] 하드 스탑 (-3% 도달: {profit_rate:.1f}%)")
                continue

            # (2) Trailing Stop: 수익 5% 돌파 후 고점 대비 -2% 하락
            if profit_rate >= 5.0 or peak_price > p_item['avg_price'] * 1.05:
                if drop_from_peak >= 2.0:
                    self.sell(code, current_price, reason=f"[보수] 트레일링 스탑 (고점대비 -2% 하락: {drop_from_peak:.1f}%)")
                    continue

            # (3) Time Cut: T+3 (진입일 포함 4영업일째 종가)
            try:
                entry_date = datetime.strptime(p_item.get('entry_date', p_item.get('buy_date', today.strftime('%Y-%m-%d'))), '%Y-%m-%d')
                diff_days = (today - entry_date).days
                if diff_days >= 3:
                    self.sell(code, current_price, reason=f"[보수] 타임 컷 (보유 {diff_days}일 경과)")
                    continue
            except: pass

        # 2. 진입 로직 (10% 비중)
        target_amount = self.initial_cash / 10
        for stock in candidates[:10]:
            code = stock['code']
            if code in self.state['portfolio']: continue
            
            price = float(stock.get('price', stock.get('현재가', 0)))
            if price <= 0: continue
            
            qty = int(target_amount / price)
            if qty > 0:
                reason = stock.get('posts_summary', '[보수] 안정적 진입 시그널')
                self.buy(code, stock.get('name', stock.get('종목명', 'Unknown')), price, qty, reason=reason)

        return self.calculate_stats(current_prices={c: s.get('price', s.get('현재가', 0)) for c, s in candidate_map.items()})
