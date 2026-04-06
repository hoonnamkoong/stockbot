import json
import os
import datetime

PORTFOLIO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'virtual_portfolio.json')
BALANCE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'virtual_balance.json')

class VirtualPortfolioManager:
    """
    [Simulated Vault] 가상 시뮬레이션 매매 및 잔고 관리 전담.
    실거래 API(KIS)를 절대 호출하지 않으며 로컬 JSON만 업데이트합니다.
    """
    def __init__(self):
        self.filepath = PORTFOLIO_FILE
        self.balance_path = BALANCE_FILE
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        self.init_portfolio()

    def init_portfolio(self):
        if not os.path.exists(self.filepath):
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
        if not os.path.exists(self.balance_path):
            with open(self.balance_path, 'w', encoding='utf-8') as f:
                json.dump({"cash": 3000000, "invested": 0}, f, ensure_ascii=False, indent=2)

    def get_portfolio(self):
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return {}

    def get_balance(self):
        try:
            with open(self.balance_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return {"cash": 3000000, "invested": 0}

    def save_all(self, port, balance):
        try:
            # Atomic save to avoid data corruption
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(port, f, ensure_ascii=False, indent=2)
            with open(self.balance_path, 'w', encoding='utf-8') as f:
                json.dump(balance, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[VPM] Save Critical Error: {e}")
            return False

    def buy_stock(self, code, name, price, quantity):
        """
        [지시사항 6] 실거래와 가상 매매의 엄격한 물리적 분리.
        전략 모듈에서 계산된 수량만큼 가상 자산을 업데이트합니다.
        [V8.4.1] 국내 주식 표준 수수료(0.015%) 반영
        """
        if quantity <= 0: return None
        
        port = self.get_portfolio()
        balance = self.get_balance()
        
        # [V8.4.1] 매수 비용 = (수량 * 가격) + 수수료(0.015%)
        base_cost = quantity * price
        fee = base_cost * 0.00015
        actual_cost = base_cost + fee
        
        # [Safety Logic] 잔고 부족 재검증 (Double Check)
        if balance['cash'] < actual_cost:
            print(f"[VPM] 🚫 {name} 매수 거부: 예수금 부족 (필요: {actual_cost:,.0f}원, 보유: {balance['cash']:,.0f}원)")
            return None

        # 업데이트
        if code in port:
            old_qty = port[code].get('quantity', 0)
            old_avg = port[code].get('average_buy_price', 0.0)
            new_qty = old_qty + quantity
            # 평단가 계산 시 수수료 포함 실제 매입가 기준
            new_avg = ((old_qty * old_avg) + actual_cost) / new_qty
            port[code]['quantity'] = new_qty
            port[code]['average_buy_price'] = new_avg
        else:
            port[code] = {
                'name': name,
                'quantity': quantity,
                'average_buy_price': actual_cost / quantity, # 수수료 포함 평단가
                'buy_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        
        balance['cash'] -= actual_cost
        balance['invested'] += actual_cost
        self.save_all(port, balance)
        print(f"[VPM] ✅ {name} {quantity}주 매수 완료 (비용: {actual_cost:,.0f}원, 수수료: {fee:,.0f}원 포함)")
        return port[code]

    def sell_stock(self, code, current_price, sell_qty=None):
        """
        [지시사항] 매도 대금 정산 로직이 포함된 V2 매도 함수
        [V8.4.1] 수수료(0.015%) 및 세금(0.18%) 차감 반영
        """
        if current_price <= 0: return None
        port, balance = self.get_portfolio(), self.get_balance()
        if code not in port: return None
        
        current_q = port[code]['quantity']
        qty_to_sell = current_q if sell_qty is None else min(sell_qty, current_q)
        
        # [V8.4.1] 가상 잔고에 매도 대금 입금 (현재가 기준 정산 - 수수료/세금 차감)
        gross_amount = qty_to_sell * current_price
        fee = gross_amount * 0.00015
        tax = gross_amount * 0.0018
        net_proceeds = gross_amount - fee - tax
        
        balance['cash'] += net_proceeds
        
        # 순자산 가치 재계산 (평단가 기준 투자금액 차감)
        avg_price = port[code].get('average_buy_price', current_price)
        balance['invested'] -= (qty_to_sell * avg_price)

        # 수량 차감 또는 포트폴리오에서 삭제
        if qty_to_sell >= current_q:
            del port[code]
        else:
            port[code]['quantity'] -= qty_to_sell
            
        self.save_all(port, balance)
        print(f"[VPM] 🚨 {code} {qty_to_sell}주 매도 완료 (정산 대금: {net_proceeds:,.0f}원, 수수료: {fee:,.0f}원, 세금: {tax:,.0f}원 차감)")
        return {"sold_qty": qty_to_sell, "sell_amount": net_proceeds}
