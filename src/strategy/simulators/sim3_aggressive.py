from .base_simulator import BaseSimulator
from datetime import datetime

class AggressiveSimulator(BaseSimulator):
    """
    [Sim 3] 공격적 추세추종형 (Aggressive - Scale-out & Momentum)
    - 3M 초기화 후 개시
    - Scale-out: +10% 수익 시 50% 분할 익절
from .base_simulator import BaseSimulator
from datetime import datetime

class AggressiveSimulator(BaseSimulator):
    """
    [Sim 3] 공격적 추세추종형 (Aggressive - Scale-out & Momentum)
    - 3M 초기화 후 개시
    - Scale-out: +10% 수익 시 50% 분할 익절
    - Runner: 대량 매도 후 남은 물량은 전일 종가 대비 -5% 하락 시 전량 매도
    - Wide Stop: -7%
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("Aggressive", initial_cash) # 파일명: sim_aggressive_state.json

    def run(self, candidates, current_prices=None):
        """
        [Aggressive] 통합 인터페이스
        """
        candidate_map = {s['code']: s for s in candidates}
        portfolio_codes = list(self.state['portfolio'].keys())

        # 1. 청산 로직 (Scale-out / Stop / Runner)
        for code in portfolio_codes:
            p_item = self.state['portfolio'][code]
            stock = candidate_map.get(code)
            
            # 현재가 확보 (candidates에 없으면 평단가 활용)
            current_price = stock.get('price', stock.get('현재가', p_item['avg_price'])) if stock else p_item['avg_price']
            if current_price <= 0: continue
            
            # 수익률 계산
            profit_rate = (current_price - p_item['avg_price']) / p_item['avg_price'] * 100
            
            # (1) Wide Stop: -7%
            if profit_rate <= -7.0:
                self.sell(code, current_price, reason=f"[공격] 와이드 스탑 (-7% 도달: {profit_rate:.1f}%)")
                continue

            # (2) Scale-out: +10% 시 50% 분할 익절
            is_scaled = p_item.get('is_scaled_out', False)
            if not is_scaled and profit_rate >= 10.0:
                qty_to_sell = p_item['quantity'] // 2
                if qty_to_sell > 0:
                    self.sell(code, current_price, quantity=qty_to_sell, reason=f"[공격] 분할 익절 (+10% 돌파: {profit_rate:.1f}%)")
                    # 분할 매도 후 플래그는 BaseSimulator.sell에서 설정함
                continue

            # (3) Runner: 절반 매도 후 남은 물량 처리 (전일 종가 대비 -5% 하락 시)
            if is_scaled:
                # 전일 종가 정보가 후보 리스트에 있는지 확인 (보통 change_rate를 통해 현재가/전일종가 계산 가능)
                # change_rate = (current - prev) / prev * 100 
                # -> prev = current / (1 + change_rate/100)
                change_rate_raw = stock.get('change_rate', stock.get('등락률', 0)) if stock else 0
                if isinstance(change_rate_raw, str):
                    change_rate = float(change_rate_raw.replace('%', '').replace('+', ''))
                else:
                    change_rate = float(change_rate_raw)
                prev_close = current_price / (1 + change_rate/100) if change_rate != 0 else current_price
                
                # 전일 종가 대비 -5% 하락한 음봉 발생 시 전량 청산
                if current_price < prev_close * 0.95:
                    self.sell(code, current_price, reason=f"[공격] 추세 꺾임 (전일비 -5% 하락)")
                    continue

        # 2. 진입 로직 (10% 비중)
        target_amount = self.initial_cash / 10
        for stock in candidates[:10]:
            code = stock['code']
            if code in self.state['portfolio']: continue
            
            price = float(stock.get('price', stock.get('현재가', 0)))
            if price <= 0: continue
            
            qty = int(target_amount / price)
            if qty > 0:
                reason = stock.get('posts_summary', '[공격] 적극적 지향형 시그널')
                self.buy(code, stock.get('name', stock.get('종목명', 'Unknown')), price, qty, reason=reason)

        # [V8.9.9.48 Hotfix] 매매 결과와 관계없이 성과 지표 상시 업데이트 및 저장
        if current_prices is None:
            current_prices = {c: s.get('price', s.get('현재가', 0)) for c, s in candidate_map.items()}
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
