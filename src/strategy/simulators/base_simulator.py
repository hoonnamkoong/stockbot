import json
import os
import datetime
import math
import csv

class TradeLog:
    """
    [V8.5.0] 단일 매매 기록 데이터 구조
    """
    def __init__(self, symbol, side, price, qty, reason):
        self.timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.symbol = symbol
        self.side = side # BUY or SELL
        self.price = price
        self.qty = qty
        self.reason = reason

class BaseSimulator:
    """
    [Strategy DNA Engine] 모든 시뮬레이터의 부모 클래스.
    - 자산 관리 (Buy/Sell), 매매 기록 (TradeLog/CSV)
    - 5대 KPI 산출 및 0-100점 정규화 로직
    """
    def __init__(self, name, initial_cash=3000000):
        self.name = name
        self.initial_cash = initial_cash
        self.data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'data')
        os.makedirs(self.data_dir, exist_ok=True)
        
        self.state_file = os.path.join(self.data_dir, f"sim_{name.lower()}_state.json")
        self.log_file = os.path.join(self.data_dir, f"sim_{name.lower()}_log.json")
        self.csv_file = os.path.join(self.data_dir, f"trade_history_sim_{name.lower()}.csv")
        
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
            "peak_nav": self.initial_cash,
            "daily_trades": [] # [{date, is_win}]
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
        # 1. JSON Log (Internal)
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

        # 2. CSV Log (Transparency)
        file_exists = os.path.exists(self.csv_file)
        with open(self.csv_file, 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "symbol", "action", "price", "quantity", "total_amount", "reason"])
            writer.writerow([
                log_entry['timestamp'], f"{name}({code})", action, 
                f"{price:,.0f}", quantity, f"{(quantity * price):,.0f}", reason
            ])

    def buy(self, code, name, price, quantity, reason=""):
        cost = quantity * price
        fee = cost * 0.00015
        total_cost = cost + fee
        
        if self.state['cash'] < total_cost: return False
            
        self.state['cash'] -= total_cost
        self.state['invested'] += cost
        
        if code in self.state['portfolio']:
            old_q = self.state['portfolio'][code].get('quantity', 0)
            old_p = self.state['portfolio'][code].get('avg_price', self.state['portfolio'][code].get('price', 0))
            new_q = old_q + quantity
            new_p = ((old_q * old_p) + cost) / new_q
            self.state['portfolio'][code]['quantity'] = new_q
            self.state['portfolio'][code]['avg_price'] = new_p
        else:
            self.state['portfolio'][code] = {
                "name": name, "quantity": quantity, "avg_price": price, 
                "buy_date": datetime.datetime.now().strftime('%Y-%m-%d')
            }
            
        self.log_trade("BUY", code, name, quantity, price, reason)
        self.save_state()
        return True

    def sell(self, code, price, quantity=None, reason=""):
        if code not in self.state['portfolio']: return False
            
        p_item = self.state['portfolio'][code]
        q_to_sell = quantity if quantity is not None else p_item['quantity']
        q_to_sell = min(q_to_sell, p_item['quantity'])
        
        gross = q_to_sell * price
        fee = gross * 0.00015
        tax = gross * 0.0018
        net = gross - fee - tax
        
        # 승률 계산용 (당일 승률 추적)
        is_win = net > (q_to_sell * p_item['price'])
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        self.state.setdefault('daily_trades', []).append({"date": today_str, "is_win": is_win})

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
        logs = []
        if os.path.exists(self.log_file):
            with open(self.log_file, 'r', encoding='utf-8') as f:
                logs = json.load(f)
                
        trades = []
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
        
        win_rate = (len([t for t in trades if t > 0]) / len(trades) * 100) if trades else 0
        
        # [V8.5.0] 당일 승률 산출
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        today_trades = [t for t in self.state.get('daily_trades', []) if t['date'] == today_str]
        daily_win_rate = (len([t for t in today_trades if t['is_win']]) / len(today_trades) * 100) if today_trades else 0

        gross_profit = sum([t for t in trades if t > 0])
        gross_loss = abs(sum([t for t in trades if t < 0]))
        pf = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)
        
        current_nav = self.state['cash'] + self.state['invested']
        mdd = 0
        peak = 0
        for nav in self.state.get('history', []):
            if nav > peak: peak = nav
            dd = (peak - nav) / peak * 100 if peak > 0 else 0
            if dd > mdd: mdd = dd
            
        freq = len(logs) / max(1, (len(self.state.get('history', [])) or 1))
        total_vol = sum([l['amount'] for l in logs])
        avg_nav = sum(self.state.get('history', [self.initial_cash])) / max(1, len(self.state.get('history', [self.initial_cash])))
        turnover = total_vol / avg_nav
        
        return {
            "cash": self.state['cash'],
            "total_asset": current_nav,
            "profit_rate": ((current_nav - self.initial_cash) / self.initial_cash) * 100,
            "holdings_count": len(self.state['portfolio']),
            "win_rate": win_rate,
            "daily_win_rate": daily_win_rate,
            "profit_factor": pf,
            "mdd": mdd,
            "frequency": freq,
            "turnover": turnover
        }

    def get_normalized_stats(self):
        raw = self.calculate_stats()
        norm = {
            "승률": min(100, raw['win_rate'] * 1.25),
            "수익팩터": min(100, raw['profit_factor'] * 33.3),
            "MDD": max(0, 100 - raw['mdd'] * 5),
            "거래빈도": min(100, raw['frequency'] * 50),
            "자본회전율": min(100, raw['turnover'] * 10)
        }
        return {"raw": raw, "normalized": norm}
