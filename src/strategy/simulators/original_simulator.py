from .base_simulator import BaseSimulator

class OriginalSimulator(BaseSimulator):
    """
    [Sim 1] 1/N 동일 비중 종가 베팅 전략
    - 후보군 N개에 대해 가용 예수금을 동일하게 배분하여 매수합니다.
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("Original", initial_cash)

    def execute_strategy(self, candidates):
        """
        [Algorithm] N개 종목에 대해 가용 예수금을 동일하게 배분
        """
        if not candidates:
            return
            
        # 가용 예수금의 95%만 매수에 활용 (수수료 대비)
        available_cash = self.state['cash'] * 0.95
        if available_cash < 10000: return
        
        # 최대 5종목까지 분산 투자 (N=5 가정)
        n = min(5, len(candidates))
        per_stock_cash = available_cash / n
        
        for stock in candidates[:n]:
            code = stock['code']
            name = stock['name']
            price = float(stock.get('price', 0))
            
            if price <= 0: continue
            
            # 이미 보유 중이면 추가 매수하지 않음 (단순화)
            if code in self.state['portfolio']: continue
            
            qty = int(per_stock_cash / price)
            if qty > 0:
                self.buy(code, name, price, qty, reason="Sim 1: 1/N 균등 배분")

    def check_liquidation(self, current_prices):
        """
        [Standard Exit] T+2일 경과 시 전량 매도
        """
        today = datetime.datetime.now()
        to_sell = []
        
        for code, item in self.state['portfolio'].items():
            buy_date = datetime.datetime.strptime(item['buy_date'], '%Y-%m-%d')
            if (today - buy_date).days >= 2:
                to_sell.append(code)
                
        for code in to_sell:
            price = current_prices.get(code, 0)
            if price > 0:
                self.sell(code, price, reason="Sim 1: T+2 시간 청산")
