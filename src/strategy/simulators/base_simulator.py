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
    - V8.6.2: 상태 영속성(JSON), 실시간 NAV 산출, 3M 초기화
    """
    def __init__(self, name, initial_cash=3000000):
        self.name = name
        self.initial_cash = initial_cash
        self.data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'data')
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 상태 및 로그 파일 경로
        self.state_file = os.path.join(self.data_dir, f"sim_{name.lower()}_state.json")
        self.log_file = os.path.join(self.data_dir, f"sim_{name.lower()}_log.json")
        self.csv_file = os.path.join(self.data_dir, f"trade_history_sim_{name.lower()}.csv")
        
        self.load_state()

    def load_state(self):
        """[V8.6.2 Hotfix] 상태 로드 및 마이그레이션 안전장치 (버그 수정)"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 수정: cash가 0 이상(>=)인지 확인 (풀매수 시 현금 0원 허용)
                # 추가로 portfolio 키가 정상적으로 존재하는지 확인
                if 'cash' in data and data['cash'] >= 0 and 'portfolio' in data:
                    self.state = data
                    # 혹시 예전 데이터라 initial_cash가 없으면 추가
                    if 'initial_cash' not in self.state:
                        self.state['initial_cash'] = self.initial_cash
                else:
                    print(f"[System] {self.name} 상태 데이터 오류 감지. 초기화 진행.")
                    self.reset_state()
            except Exception as e:
                print(f"[System] {self.name} 상태 로드 실패 ({e}). 초기화 진행.")
                self.reset_state()
        else:
            self.reset_state()

    def reset_state(self):
        """[V8.6.2 Hotfix] 3,000,000원 클린 시작"""
        print(f"[Sim] {self.name} 상태를 3,000,000원으로 초기화합니다.")
        self.state = {
            "initial_cash": self.initial_cash,
            "cash": self.initial_cash,
            "invested": 0,
            "portfolio": {},
            "peak_nav": self.initial_cash,
            "history": [self.initial_cash],
            "daily_trades": []
        }
        self.save_state()

    def save_state(self):
        """상태 영속성 저장"""
        current_nav = self.state['cash'] + self.state['invested']
        if current_nav > self.state.get('peak_nav', 0):
            self.state['peak_nav'] = current_nav
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def log_trade(self, action, code, name, quantity, price, reason):
        """매매 이력 기록 (JSON & CSV)"""
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
        # JSON Log
        logs = []
        if os.path.exists(self.log_file):
            try:
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
            except: pass
        logs.append(log_entry)
        with open(self.log_file, 'w', encoding='utf-8') as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)

        # CSV Log
        file_exists = os.path.exists(self.csv_file)
        with open(self.csv_file, 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "symbol", "action", "price", "quantity", "total_amount", "reason"])
            writer.writerow([
                log_entry['timestamp'], f"{name}({code})", action, 
                int(price), quantity, int(quantity * price), reason
            ])

    def buy(self, code, name, price, quantity, reason=""):
        """매수 로직: 포트폴리오 즉시 업데이트 및 저장"""
        cost = quantity * price
        fee = cost * 0.00015
        total_cost = cost + fee
        if self.state['cash'] < total_cost: return False
        self.state['cash'] -= total_cost
        self.state['invested'] += cost
        if code in self.state['portfolio']:
            old_q = self.state['portfolio'][code]['quantity']
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
        """매도 로직: 포트폴리오 즉시 업데이트 및 저장"""
        if code not in self.state['portfolio']: return False
        p_item = self.state['portfolio'][code]
        q_to_sell = quantity if quantity is not None else p_item['quantity']
        q_to_sell = min(q_to_sell, p_item['quantity'])
        gross = q_to_sell * price
        fee = gross * 0.00015
        tax = gross * 0.0018
        net = gross - fee - tax
        avg_price = p_item.get('avg_price', 0)
        is_win = net > (q_to_sell * avg_price)
        self.state['cash'] += net
        self.state['invested'] -= (q_to_sell * avg_price)
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        self.state.setdefault('daily_trades', []).append({"date": today_str, "is_win": is_win})
        if q_to_sell >= p_item['quantity']:
            del self.state['portfolio'][code]
        else:
            self.state['portfolio'][code]['quantity'] -= q_to_sell
        self.log_trade("SELL", code, p_item['name'], q_to_sell, price, reason)
        self.save_state()
        return True

    def calculate_stats(self, current_prices=None):
        """V8.6.2 실시간 자산 총액 산출 로직"""
        current_prices = current_prices or {}
        eval_invested = 0
        for code, item in self.state['portfolio'].items():
            cur_p = current_prices.get(code, item['avg_price'])
            eval_invested += (item['quantity'] * cur_p)
        current_nav = self.state['cash'] + eval_invested
        logs = []
        if os.path.exists(self.log_file):
            try:
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
            except: pass
        win_rate = 0
        pf = 1.0
        if logs:
            trades = []
            temp_buy = {}
            for l in logs:
                c = l['code']
                if l['action'] == "BUY": temp_buy.setdefault(c, []).append(l)
                elif l['action'] == "SELL" and c in temp_buy and temp_buy[c]:
                    b = temp_buy[c].pop(0)
                    trades.append(l['amount'] - b['amount'])
            if trades:
                win_rate = (len([t for t in trades if t > 0]) / len(trades) * 100)
                gp = sum([t for t in trades if t > 0])
                gl = abs(sum([t for t in trades if t < 0]))
                pf = gp / gl if gl > 0 else (gp if gp > 0 else 1.0)
        mdd = 0
        peak = 0
        if not self.state.get('history'): self.state['history'] = [self.initial_cash]
        for nav in self.state['history']:
            if nav > peak: peak = nav
            dd = (peak - nav) / peak * 100 if peak > 0 else 0
            if dd > mdd: mdd = dd
        return {
            "cash": self.state['cash'],
            "total_asset": current_nav,
            "profit_rate": ((current_nav - self.initial_cash) / self.initial_cash) * 100,
            "holdings_count": len(self.state['portfolio']),
            "win_rate": win_rate,
            "profit_factor": pf,
            "mdd": mdd,
            "current_prices": current_prices
        }

    def get_normalized_stats(self, current_prices=None):
        raw = self.calculate_stats(current_prices)
        norm = {
            "승률": min(100, raw['win_rate'] * 1.25),
            "수익팩터": min(100, raw['profit_factor'] * 33.3),
            "MDD": max(0, 100 - raw['mdd'] * 5),
            "자산평가": min(100, (raw['total_asset'] / self.initial_cash) * 50)
        }
        return {"raw": raw, "normalized": norm, "portfolio": self.state['portfolio']}
