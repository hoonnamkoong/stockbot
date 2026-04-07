import json
import os
import datetime
import math

class BaseSimulator:
    """
    [Strategy DNA Engine] 모든 시뮬레이터의 부모 클래스.
    - 자산 관리 (Buy/Sell), 매매 기록 (TradeLog)
    - 5대 KPI 산출 및 0-100점 정규화 로직
    """
    def __init__(self, name, initial_cash=3000000):
        self.name = name
        self.initial_cash = initial_cash
        self.data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'data')
        os.makedirs(self.data_dir, exist_ok=True)
        
        self.state_file = os.path.join(self.data_dir, f"sim_{name.lower()}_state.json")
        self.log_file = os.path.join(self.data_dir, f"sim_{name.lower()}_log.json")
        
        self.load_state()

    def load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    self.state = json.load(f)
            except:
                self.reset_state()
        else:
            self.reset_state()

    def reset_state(self):
        self.state = {
            "cash": self.initial_cash,
            "invested": 0,
            "portfolio": {},
            "history": [], # Daily NAV history for MDD
            "peak_nav": self.initial_cash
        }
        self.save_state()

    def save_state(self):
        # NAV 갱신
        current_nav = self.state['cash'] + self.state['invested']
        if current_nav > self.state.get('peak_nav', 0):
            self.state['peak_nav'] = current_nav
            
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def log_trade(self, action, code, name, quantity, price, reason):
        log_entry = {
            "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "action": action,
            "code": code,
            "name": name,
            "quantity": quantity,
            "price": price,
            "amount": quantity * price,
            "reason": reason
        }
        
        logs = []
        if os.path.exists(self.log_file):
            try:
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
            except: pass
            
        logs.append(log_entry)
        with open(self.log_file, 'w', encoding='utf-8') as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)

    def buy(self, code, name, price, quantity, reason=""):
        # V8.4.1 표준 수수료 0.015%
        cost = quantity * price
        fee = cost * 0.00015
        total_cost = cost + fee
        
        if self.state['cash'] < total_cost:
            return False
            
        self.state['cash'] -= total_cost
        self.state['invested'] += cost
        
        if code in self.state['portfolio']:
            old_q = self.state['portfolio'][code]['quantity']
            old_p = self.state['portfolio'][code]['price']
            new_q = old_q + quantity
            new_p = ((old_q * old_p) + cost) / new_q
            self.state['portfolio'][code]['quantity'] = new_q
            self.state['portfolio'][code]['price'] = new_p
        else:
            self.state['portfolio'][code] = {
                "name": name, "quantity": quantity, "price": price, 
                "buy_date": datetime.datetime.now().strftime('%Y-%m-%d')
            }
            
        self.log_trade("BUY", code, name, quantity, price, reason)
        self.save_state()
        return True

    def sell(self, code, price, quantity=None, reason=""):
        if code not in self.state['portfolio']:
            return False
            
        p_item = self.state['portfolio'][code]
        q_to_sell = quantity if quantity is not None else p_item['quantity']
        q_to_sell = min(q_to_sell, p_item['quantity'])
        
        # 수수료 0.015%, 세금 0.18%
        gross = q_to_sell * price
        fee = gross * 0.00015
        tax = gross * 0.0018
        net = gross - fee - tax
        
        self.state['cash'] += net
        self.state['invested'] -= (q_to_sell * p_item['price'])
        
        if q_to_sell >= p_item['quantity']:
            del self.state['portfolio'][code]
        else:
            self.state['portfolio'][code]['quantity'] -= q_to_sell
            
        self.log_trade("SELL", code, p_item['name'], q_to_sell, price, reason)
        self.save_state()
        return True

    def calculate_stats(self):
        """
        [DNA Logic] 5대 KPI 산출
        """
        logs = []
        if os.path.exists(self.log_file):
            with open(self.log_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
                
        trades = []
        # 매수/매도 매칭을 통한 개별 트레이드 손익 계산 (단순화)
        temp_buy = {}
        for l in logs:
            code = l['code']
            if l['action'] == "BUY":
                if code not in temp_buy: temp_buy[code] = []
                temp_buy[code].append(l)
            elif l['action'] == "SELL":
                if code in temp_buy and temp_buy[code]:
                    b = temp_buy[code].pop(0)
                    profit = l['amount'] - b['amount']
                    trades.append(profit)
        
        # 1. 승률
        win_rate = (len([t for t in trades if t > 0]) / len(trades) * 100) if trades else 0
        
        # 2. PF (Profit Factor)
        gross_profit = sum([t for t in trades if t > 0])
        gross_loss = abs(sum([t for t in trades if t < 0]))
        pf = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)
        
        # 3. MDD (Max Drawdown)
        # NAV 히스토리를 기반으로 함 (여기서는 단순화하여 누적 시뮬레이션 NAV 사용)
        current_nav = self.state['cash'] + self.state['invested']
        self.state['history'].append(current_nav)
        
        mdd = 0
        peak = 0
        for nav in self.state['history']:
            if nav > peak: peak = nav
            dd = (peak - nav) / peak * 100 if peak > 0 else 0
            if dd > mdd: mdd = dd
            
        # 4. 거래 빈도 (Total trades / duration in days) - 샘플로 30일 기준
        freq = len(logs) / max(1, (len(self.state['history']) or 1))
        
        # 5. 자본 회전율 (Total Volume / Avg NAV)
        total_vol = sum([l['amount'] for l in logs])
        avg_nav = sum(self.state['history']) / len(self.state['history']) if self.state['history'] else self.initial_cash
        turnover = total_vol / avg_nav
        
        return {
            "win_rate": win_rate,
            "profit_factor": pf,
            "mdd": mdd,
            "frequency": freq,
            "turnover": turnover
        }

    def get_normalized_stats(self):
        raw = self.calculate_stats()
        
        # Normalization (0~100)
        norm = {
            "승률": min(100, raw['win_rate'] * 1.25), # 80% Win Rate = 100pts
            "수익팩터": min(100, raw['profit_factor'] * 33.3), # PF 3.0 = 100pts
            "MDD": max(0, 100 - raw['mdd'] * 5), # MDD 20% = 0pts, 0% = 100pts
            "거래빈도": min(100, raw['frequency'] * 50), # 일 2회 거래 = 100pts
            "자본회전율": min(100, raw['turnover'] * 10) # 10배 회전 = 100pts
        }
        
        return {
            "raw": raw,
            "normalized": norm
        }
