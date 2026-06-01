import json
import csv
import os
import datetime
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
    BUY_FEE_RATE = 0.00015   # 매수 수수료율
    SELL_FEE_RATE = 0.00015  # 매도 수수료율
    SELL_TAX_RATE = 0.0018   # 증권거래세율
    IS_ANALYZER = False      # True면 매매하지 않는 분석기(리베로). reset 시 자본 부여 제외

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
                with open(self.state_file, 'r', encoding='utf-8-sig') as f:
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
        print(f"[Sim] {self.name} 상태를 {self.initial_cash:,}원으로 초기화합니다.")
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
        
        # [Fix] 상태 초기화 시 기존 로그 및 CSV 파일도 함께 삭제하여 히스토리 불일치 해결
        if os.path.exists(self.log_file):
            try:
                os.remove(self.log_file)
            except Exception as e:
                print(f"[Warning] {self.name} 로그 파일 삭제 실패: {e}")
                
        if os.path.exists(self.csv_file):
            try:
                os.remove(self.csv_file)
            except Exception as e:
                print(f"[Warning] {self.name} CSV 파일 삭제 실패: {e}")
                
        self.save_state()

    def save_state(self, current_prices=None):
        """상태 및 실시간 분석 통계 영속성 저장"""
        try:
            current_nav = self.state['cash'] + self.state['invested']
            if current_nav > self.state.get('peak_nav', 0):
                self.state['peak_nav'] = current_nav
            
            # [V8.9.9.12] 저장 시점에 통계를 계산하여 포함 (Radar Chart 연동용)
            # [V8.9.9.35 Fix] 저장 시점에 통계를 계산하여 포함 (수익률 동기화 필수)
            # [Fix] current_prices가 제공된 경우(run() 종료 시)에만 통계 갱신 — buy/sell 중복 파싱 제거
            if current_prices is not None:
                try:
                    stats = self.calculate_stats(current_prices)
                    full_stats = self.get_normalized_stats(current_prices)
                    
                    self.state['raw_stats'] = stats
                    self.state['normalized_stats'] = full_stats['normalized']
                    
                    calc_fees = stats.get('total_fees', 0)
                    if calc_fees > self.state.get('total_fees', 0):
                        self.state['total_fees'] = calc_fees
                except Exception as e:
                    print(f"[Sim Warning] {self.name} 성과 지표 업데이트 건너뜀: {e}")

        except Exception as e:
            print(f"[Sim Critical] {self.name} 상태 필드 접근 오류: {e}")

        # 어떠한 경우에도 파일은 최대한 저장 시도
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Sim Critical] {self.name} 파일 쓰기 실패: {e}")

    def log_trade(self, action, code, name, quantity, price, reason):
        """매매 이력 기록 (CSV append only — JSON 이중 기록 제거로 I/O 최적화)"""
        timestamp = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
        file_exists = os.path.exists(self.csv_file)
        with open(self.csv_file, 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "symbol", "action", "price", "quantity", "total_amount", "reason"])
            writer.writerow([
                timestamp, f"{name}({code})", action,
                int(price), quantity, int(quantity * price), reason
            ])

    def buy(self, code, name, price, quantity, reason=""):
        """매수 로직: 포트폴리오 즉시 업데이트 및 저장"""
        cost = quantity * price
        fee = cost * self.BUY_FEE_RATE
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
        fee = gross * self.SELL_FEE_RATE
        tax = gross * self.SELL_TAX_RATE
        net = gross - fee - tax
        self.state['total_fees'] = self.state.get('total_fees', 0) + (fee + tax)
        avg_price = p_item.get('avg_price', 0)
        is_win = net > (q_to_sell * avg_price)
        self.state['cash'] += net
        self.state['invested'] = max(0, self.state['invested'] - (q_to_sell * avg_price))
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

    def calculate_atr(self, sparkline_price: list, period: int = 5) -> float:
        """[V60.1 Patch] 변동성(ATR) 계산 및 하한값(Fallback) 설정"""
        if len(sparkline_price) < 2:
            return 1.0 # 최소 변동폭 1원 설정 (나누기 0 방지)
        
        diffs = []
        for i in range(1, len(sparkline_price)):
            diffs.append(abs(sparkline_price[i] - sparkline_price[i-1]))
        
        if not diffs: return 1.0
        atr = sum(diffs[-period:]) / len(diffs[-period:])
        return max(atr, 1.0) # ATR이 0이 되지 않도록 보장

    def validate_tick_power(self, stock_data: dict, threshold: float = 120.0) -> bool:
        """[V60.0] 수급의 힘(체결강도)이 임계치를 넘는지 확인합니다.
        KIS API 실패로 0.0인 경우, 데이터 없음 ≠ 수급 나쁨이므로 조건 스킵(통과).
        """
        tp = float(stock_data.get('tick_power', 0.0))
        if tp == 0.0:
            return True  # KIS 실패 시 데이터 없음으로 간주, 조건 면제
        return tp >= threshold

    def calculate_adx(self, sparkline_price: list) -> float:
        """
        [V2] ADX (Average Directional Index) 근사치 계산 (Efficiency Ratio 사용)
        - sparkline_price: 최근 종가 리스트 (과거 -> 최신)
        - 반환값: 0 ~ 100 사이의 추세 강도. 20 미만은 횡보, 25 이상은 강한 추세장으로 판단.
        """
        if len(sparkline_price) < 2:
            return 0.0
            
        direction = abs(sparkline_price[-1] - sparkline_price[0])
        volatility = sum(abs(sparkline_price[i] - sparkline_price[i-1]) for i in range(1, len(sparkline_price)))
        
        if volatility == 0:
            return 0.0
            
        er = direction / volatility
        return er * 100.0

    def calc_period_change(self, sparkline_price: list) -> float:
        """[Sim4/6] 기간 변동률(%). 프로덕션 후보에 period_change_rate가 없어 sparkline 종가로 계산."""
        if not sparkline_price or len(sparkline_price) < 2:
            return 0.0
        start = sparkline_price[0]
        end = sparkline_price[-1]
        if start <= 0:
            return 0.0
        return (end - start) / start * 100.0

    def parse_change_rate(self, stock_data: dict) -> float:
        """당일 등락률을 실수로 정제. change_rate는 '±X.XX%' 문자열로 저장됨."""
        cr = stock_data.get('change_rate', stock_data.get('daily_change_rate', 0))
        if isinstance(cr, str):
            try:
                return float(cr.replace('%', '').replace('+', '').strip())
            except ValueError:
                return 0.0
        return float(cr or 0)

    def calculate_mfhs2_score(self, stock_data: dict, current_month: int) -> int:
        """
        [Sim2 MFHS2] 다중 필터 하이브리드 수급 동승 전략 스코어 산출
        - A(수급 40점) + B(발산 40점) + C(계절성 20점) = 총합 산출
        """
        score = 0
        
        # [조건 A] 외국인 수급 (40점)
        f_change = stock_data.get('foreign_change', 0)
        if isinstance(f_change, str):
            try:
                f_change = float(f_change.replace('%', '').replace('+', '').strip())
            except ValueError:
                f_change = 0.0
        
        # 외국인 비중이 전일 대비 증가했다면 40점
        if f_change > 0:
            score += 40
            
        # [조건 B] 감정-수급 발산 (40점)
        posts = int(stock_data.get('recent_posts_count', 0))
        sentiment = stock_data.get('sentiment', '')
        pos_percent = 0
        if 'Positive' in sentiment:
            try:
                pos_percent = float(sentiment.split('(')[1].split('%')[0])
            except:
                pass
                
        # 거래량이 터지기 전 게시판이 달아오르는 발산 현상 (Positive 60% 초과 & 게시물수 30개 이상)
        if posts >= 30 and pos_percent > 60:
            score += 40
            
        # [조건 C] 계절성 (20점)
        # 1~4월은 강세 가중치 (리밸런싱, 실적), 5월 이후는 공매도 등 보수적 접근
        if 1 <= current_month <= 4:
            score += 20
            
        return score

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

    def _load_trade_logs(self):
        """CSV에서 매매 기록을 파싱합니다 (JSON 이중 기록 제거 후 CSV가 유일한 소스)."""
        logs = []
        # [호환성] 기존 JSON 로그가 있으면 우선 사용 (마이그레이션 기간)
        if os.path.exists(self.log_file):
            try:
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if data:
                    return data
            except Exception:
                pass
        # CSV에서 파싱
        if os.path.exists(self.csv_file):
            try:
                with open(self.csv_file, 'r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        symbol = row.get('symbol', '')
                        code = symbol.split('(')[-1].rstrip(')') if '(' in symbol else symbol
                        logs.append({
                            'code': code,
                            'action': row.get('action', 'BUY'),
                            'price': float(row.get('price', '0').replace(',', '')),
                            'quantity': int(row.get('quantity', 0)),
                            'amount': float(row.get('total_amount', '0').replace(',', '')),
                            'timestamp': row.get('timestamp', '')
                        })
            except Exception as e:
                print(f"[Sim Warning] {self.name} CSV 파싱 실패: {e}")
        return logs

    def calculate_stats(self, current_prices=None):
        """성과 지표 정밀 산출"""
        current_prices = current_prices or {}
        eval_invested = 0
        for code, item in self.state['portfolio'].items():
            cur_p = current_prices.get(code, item.get('avg_price', item.get('price', 0)))
            eval_invested += (item['quantity'] * cur_p)
        current_nav = self.state['cash'] + eval_invested
        
        logs = self._load_trade_logs()
        
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
                if len(logs) > 0:
                    start_date = datetime.datetime.strptime(logs[0]['timestamp'], '%Y-%m-%d %H:%M:%S')
                    now_kst = get_kst_now().replace(tzinfo=None)
                    days = (now_kst - start_date).days + 1
                    freq = len(logs) / days
            except Exception as e:
                print(f"[Sim Warning] {self.name} 거래빈도 계산 실패: {e}")
                freq = len(logs)
 
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
