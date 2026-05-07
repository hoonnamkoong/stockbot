import json
import csv
import os
import datetime
import math
from datetime import timedelta, timezone


def get_kst_now():
    # [V8.9.9.21] 시스템 환경과 무관하게 한국 표준시(UTC+9) 강제 적용
    return datetime.datetime.now(timezone(timedelta(hours=9)))


class TradeLog:
    """
    [V8.5.0] 단일 매매 기록 데이터 구조
    """
    def __init__(self, symbol, side, price, qty, reason):
        self.timestamp = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
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
    def __init__(self, name, initial_cash=5000000):
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
        """[V8.9.9.18] 상태 로드 및 보호 로직 보강"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if not content:
                        raise ValueError("File is empty")
                    data = json.loads(content)
                
                # 필수 필드 존재 여부 확인
                if 'cash' in data and 'portfolio' in data:
                    self.state = data
                    # 신규 필드 마이그레이션
                    self.state.setdefault('initial_cash', self.initial_cash)
                    self.state.setdefault('market_index_healthy', True)
                    self.state.setdefault('peak_nav', data.get('cash', self.initial_cash))
                    self.state.setdefault('total_fees', 0)
                    self.state.setdefault('daily_trades', [])
                    self.state.setdefault('history', [self.initial_cash])
                    
                    # 포트폴리오 내 고점 데이터 보정
                    for code, item in self.state['portfolio'].items():
                        item.setdefault('peak_price', item.get('avg_price', 0))
                    
                    print(f"[Sim] {self.name} 상태 로드 성공 (잔고: {self.state['cash']:,}원)")
                else:
                    # 필드가 부족한 경우 부분 복구 시도 (초기화 대신 최대한 유지)
                    print(f"[Warning] {self.name} 필수 필드 누락. 데이터 보정 시도.")
                    self.state = data
                    self.state.setdefault('cash', self.initial_cash)
                    self.state.setdefault('portfolio', {})
            except Exception as e:
                print(f"[Critical] {self.name} 상태 파일 손상 ({e}). 백업을 확인하세요.")
                # 파일이 깨진 경우 즉시 초기화하지 않고 일단 멈추거나 기본값 설정
                self.reset_state()
        else:
            print(f"[Info] {self.name} 신규 시뮬레이터 시작 (기존 파일 없음)")
            self.reset_state()


    def reset_state(self):
        """[V8.6.2 Hotfix] 5,000,000원 클린 시작"""
        print(f"[Sim] {self.name} 상태를 5,000,000원으로 초기화합니다.")
        self.state = {
            "initial_cash": self.initial_cash,
            "cash": self.initial_cash,
            "invested": 0,
            "portfolio": {},
            "peak_nav": self.initial_cash,
            "total_fees": 0, 
            "history": [self.initial_cash],
            "daily_trades": [],
            "market_index_healthy": True # [V2] 시장 지수 상태
        }
        self.save_state()

    def save_state(self, current_prices=None):
        """상태 및 실시간 분석 통계 영속성 저장"""
        try:
            current_nav = self.state['cash'] + self.state['invested']
            if current_nav > self.state.get('peak_nav', 0):
                self.state['peak_nav'] = current_nav
            
            # [V8.9.9.12] 저장 시점에 통계를 계산하여 포함 (Radar Chart 연동용)
            # [V8.9.9.35 Fix] 저장 시점에 통계를 계산하여 포함 (수익률 동기화 필수)
            try:
                # [팩트] analyzer.get_current_prices 및 results 기반의 current_prices 주입
                stats = self.calculate_stats(current_prices)
                full_stats = self.get_normalized_stats(current_prices)
                
                self.state['raw_stats'] = stats
                self.state['normalized_stats'] = full_stats['normalized']
                
                # [V8.9.9.19] 계산된 수수료 동기화
                calc_fees = stats.get('total_fees', 0)
                if calc_fees > self.state.get('total_fees', 0):
                    self.state['total_fees'] = calc_fees
            except Exception as e:
                print(f"[Sim Warning] {self.name} 성과 지표 업데이트 건너뜀: {e}")
                pass

        except Exception as e:
            print(f"[Sim Critical] {self.name} 상태 필드 접근 오류: {e}")

        # 어떠한 경우에도 파일은 최대한 저장 시도
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Sim Critical] {self.name} 파일 쓰기 실패: {e}")

    def log_trade(self, action, code, name, quantity, price, reason):
        """매매 이력 기록 (JSON & CSV)"""
        log_entry = {
            "timestamp": get_kst_now().strftime('%Y-%m-%d %H:%M:%S'),
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
        self.state['total_fees'] = self.state.get('total_fees', 0) + fee # 수수료 누적
        if code in self.state['portfolio']:
            old_item = self.state['portfolio'][code]
            old_q = old_item['quantity']
            old_p = old_item.get('avg_price', old_item.get('price', 0))
            new_q = old_q + quantity
            new_p = ((old_q * old_p) + cost) / new_q
            self.state['portfolio'][code]['quantity'] = new_q
            self.state['portfolio'][code]['avg_price'] = new_p
            # 평균 단가가 바뀌어도 고점은 초기화하지 않거나 유지 (전략에 따라 다름)
            if price > self.state['portfolio'][code].get('peak_price', 0):
                self.state['portfolio'][code]['peak_price'] = price
        else:
            self.state['portfolio'][code] = {
                "name": name, 
                "quantity": quantity, 
                "avg_price": price, 
                "entry_date": get_kst_now().strftime('%Y-%m-%d'),
                "peak_price": price,
                "is_scaled_out": False  # [Sim 3용] 분할 매수/매도 여부
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
        self.state['total_fees'] = self.state.get('total_fees', 0) + (fee + tax) # 수수료+세금 누적
        avg_price = p_item.get('avg_price', 0)
        is_win = net > (q_to_sell * avg_price)
        self.state['cash'] += net
        self.state['invested'] -= (q_to_sell * avg_price)
        today_str = get_kst_now().strftime('%Y-%m-%d')
        self.state.setdefault('daily_trades', []).append({"date": today_str, "is_win": is_win})
        if q_to_sell >= p_item['quantity']:
            del self.state['portfolio'][code]
        else:
            self.state['portfolio'][code]['quantity'] -= q_to_sell
            self.state['portfolio'][code]['is_scaled_out'] = True # 일부 매도 발생 시 플래그 설정
        self.log_trade("SELL", code, p_item['name'], q_to_sell, price, reason)
        self.save_state()
        return True

    def update_peak_prices(self, current_prices):
        """[V2] 모든 보유 종목의 고점(Peak)을 실시간 업데이트"""
        updated = False
        for code, p_item in self.state['portfolio'].items():
            curr_p = current_prices.get(code, 0)
            if curr_p > p_item.get('peak_price', 0):
                p_item['peak_price'] = curr_p
                updated = True
        if updated:
            self.save_state()

    def check_trailing_stop(self, code, current_price, activation_pct=5.0, callback_pct=3.0):
        """
        [V2] 수익률이 activation_pct 이상 도달 후 고점 대비 callback_pct 하락 시 매도 신호
        """
        if code not in self.state['portfolio']: return False
        p_item = self.state['portfolio'][code]
        
        avg_p = p_item.get('avg_price', 0)
        peak_p = p_item.get('peak_price', avg_p)
        if avg_p <= 0: return False
        
        profit_rate = (current_price - avg_p) / avg_p * 100
        drop_from_peak = (peak_p - current_price) / peak_p * 100 if peak_p > 0 else 0
        
        # 수익이 한번이라도 5%를 찍었고, 고점에서 3% 빠지면 익절 실행
        if profit_rate >= activation_pct or peak_p > (avg_p * (1 + activation_pct/100)):
            if drop_from_peak >= callback_pct:
                return True
        return False

    def calculate_stats(self, current_prices=None):
        """성과 지표 정밀 산출"""
        current_prices = current_prices or {}
        eval_invested = 0
        for code, item in self.state['portfolio'].items():
            cur_p = current_prices.get(code, item.get('avg_price', item.get('price', 0)))
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
        turnover = 0
        freq = 0
        total_fees = self.state.get('total_fees', 0)
        
        if logs:
            trades = []
            temp_avg = {}
            total_volume = 0
            for l in logs:
                c = l.get('code', '')
                q = l.get('quantity', 0)
                p = l.get('price', 0)
                amt = l.get('amount', p * q)
                total_volume += amt
                action = l.get('action', 'BUY')
                
                if action == "BUY":
                    if c not in temp_avg:
                        temp_avg[c] = {'qty': q, 'avg_price': p}
                    else:
                        old_q = temp_avg[c]['qty']
                        old_p = temp_avg[c]['avg_price']
                        new_q = old_q + q
                        new_p = ((old_q * old_p) + (p * q)) / new_q if new_q > 0 else p
                        temp_avg[c] = {'qty': new_q, 'avg_price': new_p}
                elif action == "SELL":
                    if c in temp_avg and temp_avg[c]['qty'] > 0:
                        buy_p = temp_avg[c]['avg_price']
                        pl = (p - buy_p) * q
                        trades.append(pl)
                        temp_avg[c]['qty'] = max(0, temp_avg[c]['qty'] - q)
            
            if trades:
                win_rate = (len([t for t in trades if t > 0]) / len(trades) * 100)
                gp = sum([t for t in trades if t > 0])
                gl = abs(sum([t for t in trades if t < 0]))
                pf = gp / gl if gl > 0 else (gp if gp > 0 else 1.0)
            
            # 자본 회전율: 총 거래대금 / 초기자본
            turnover = total_volume / self.initial_cash if self.initial_cash > 0 else 0
            
            # 거래 빈도: 시작일로부터 현재까지 하루 평균 거래 횟수
            try:
                # [V8.9.9.14] 로그가 있을 때만 시간 파싱
                if len(logs) > 0:
                    start_date = datetime.datetime.strptime(logs[0]['timestamp'], '%Y-%m-%d %H:%M:%S')
                    days = (datetime.datetime.now() - start_date).days + 1
                    freq = len(logs) / days
            except: freq = len(logs)
 
            # [V8.9.9.14] 수수료 소급 계산 (state에 수수료가 0인 경우 로그 기반 추정)
            if total_fees == 0 and total_volume > 0:
                # 평균 거래 수수료+세금 약 0.1%(매수 0.015, 매도 0.2) -> 평균 0.1% 적용
                total_fees = total_volume * 0.001 
            
        mdd = 0
        peak = self.state.get('peak_nav', current_nav)
        if current_nav > peak:
            peak = current_nav
            self.state['peak_nav'] = peak
        mdd = (peak - current_nav) / peak * 100 if peak > 0 else 0
        
        return {
            "cash": self.state['cash'],
            "total_asset": current_nav,
            "profit_rate": ((current_nav - self.initial_cash) / self.initial_cash) * 100 if self.initial_cash > 0 else 0,
            "holdings_count": len(self.state['portfolio']),
            "win_rate": win_rate,
            "profit_factor": pf,
            "mdd": mdd,
            "turnover": turnover,
            "frequency": freq,
            "total_fees": total_fees,
            "current_prices": current_prices
        }

    def get_normalized_stats(self, current_prices=None):
        """[V8.9.9.12] 5대 지표 분석 결과 정규화 (Radar Chart용)"""
        raw = self.calculate_stats(current_prices)
        norm = {
            "승률": min(100, max(0, raw['win_rate'])),
            "수익팩터": min(100, raw['profit_factor'] * 20),
            "MDD": max(0, 100 - raw['mdd'] * 3), 
            "거래빈도": min(100, raw['frequency'] * 5), 
            "자본회전율": min(100, raw['turnover'] * 2)
        }
        return {"raw": raw, "normalized": norm, "portfolio": self.state['portfolio']}
