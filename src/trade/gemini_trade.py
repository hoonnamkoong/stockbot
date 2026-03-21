import os
import json
from datetime import datetime

class GeminiTrader:
    def __init__(self):
        self.portfolio_file = 'data/gemini_portfolio.json'
        
        # Trading Rules
        self.INITIAL_CASH = 3000000
        self.MAX_ALLOCATION_PER_STOCK = 0.20 # 20% max per stock
        self.FEE_BUY = 0.00015
        self.FEE_SELL = 0.00215 # 0.015% fee + 0.2% tax
        
        self.state = self._load_state()

    def _get_default_state(self):
        return {
            'cash': self.INITIAL_CASH,
            'holdings': {}, # code: {qty, avg_price, buy_date, days_held, name, target_prob}
            'trade_log': [],
            'last_update': '',
            'algo_version': 'v_unknown',
            'market_regime': 'NEUTRAL', # BULL, BEAR, NEUTRAL
            'benchmark_base': {} # {'KOSPI': 2500, ...}
        }
        
    def _load_state(self):
        if os.path.exists(self.portfolio_file):
            try:
                if os.path.getsize(self.portfolio_file) > 0:
                    with open(self.portfolio_file, 'r', encoding='utf-8') as f:
                        return json.load(f)
                else:
                    # File exists but is 0 bytes
                    print("⚠️ [Warning] Portfolio file is empty (0 bytes). Reverting to defaults.")
                    # Proactively notify Telegram once
                    try:
                        from src.telegram_manager import TelegramManager
                        notifier = TelegramManager()
                        notifier.send_message(f"⚠️ <b>데이터 유실 감지</b>\n포트폴리오 파일({self.portfolio_file})이 0바이트입니다. 임시로 기본 잔고(300만)를 로드합니다. 데이터 확인이 필요합니다.")
                    except: pass
                    return self._get_default_state()
            except Exception as e:
                error_msg = f"‼️ [Critical] Portfolio Load Failed: {e}"
                print(error_msg)
                return self._get_default_state()
                
        # Initialize defaults if not exists
        return self._get_default_state()
        
    def _save_state(self):
        os.makedirs('data', exist_ok=True)
        with open(self.portfolio_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)
            
    def _get_current_date(self):
        # KST Current Date (+9 hours)
        from datetime import timezone, timedelta
        kst = timezone(timedelta(hours=9))
        return datetime.now(kst).strftime('%Y-%m-%d')
        
    def check_exits(self, current_data):
        """
        Evaluate current holdings and execute Sells if conditions are met.
        current_data: dict of {code: {'price': 1000, 'ml_prob': 60.5}} for TODAY's scraped data
        """
        codes_to_sell = []
        current_date = self._get_current_date()
        
        # Don't double-sell today
        if self.state.get('last_update') == current_date:
            pass # We still might want to sell if price changed mid-day, but usually we do this once a day. Let's allow mid-day sells.

        for code, h in self.state['holdings'].items():
            if code in current_data:
                current_price = float(current_data[code].get('price', h['avg_price']))
                ml_prob = float(current_data[code].get('ml_prob', 50.0))
                
                # Check if it's a new day to increment days_held
                
                profit_rate = ((current_price - h['avg_price']) / h['avg_price']) * 100
                
                # Market Adaptive Rules
                regime = self.state.get('market_regime', 'NEUTRAL')
                
                # Default (Bear/Neutral)
                tp_threshold = 10.0
                max_hold_days = 7
                sl_threshold = -5.0
                
                if regime == 'BULL':
                    tp_threshold = 20.0
                    max_hold_days = 10
                    sl_threshold = -7.0
                
                sell_reason = None
                if profit_rate >= tp_threshold and ml_prob < 50.0:
                    sell_reason = f"TP ({regime} goal +{profit_rate:.1f}%) & Momentum Dropped (Prob: {ml_prob:.1f}%)"
                elif profit_rate >= (tp_threshold * 2): # Hard cap
                    sell_reason = f"Max Target Met (+{profit_rate:.1f}%)"
                elif profit_rate <= sl_threshold:
                    sell_reason = f"Stop Loss hit at {profit_rate:.1f}% (Regime: {regime})"
                elif h['days_held'] >= max_hold_days:
                    sell_reason = f"Time Stop reached ({max_hold_days} days in {regime})"
                    
                if sell_reason:
                    print(f"  [Action] SELL {code} ({h.get('name')}) - Reason: {sell_reason}")
                    sell_vol = current_price * h['qty']
                    fee = sell_vol * self.FEE_SELL
                    net_return = sell_vol - fee
                    
                    self.state['cash'] += net_return
                    self.state['trade_log'].append({
                        'date': current_date + " " + datetime.utcnow().strftime('%H:%M:%S'), 
                        'type': 'SELL', 
                        'code': code, 
                        'name': h.get('name', code),
                        'qty': h['qty'], 
                        'price': current_price, 
                        'profit_rate': profit_rate, 
                        'reason': sell_reason
                    })
                    codes_to_sell.append(code)
                else:
                    print(f"  [Hold] {code} ({h.get('name')}) - Profit: {profit_rate:.1f}%, ML Prob: {ml_prob:.1f}%")
            else:
                print(f"  [Skip] {code} ({h.get('name')}) - No today's data to evaluate exit.")
                    
        for c in codes_to_sell:
            del self.state['holdings'][c]
            
        if codes_to_sell:
            self._save_state()
        else:
            print("  [Result] No exit conditions met.")
        
    def execute_buys(self, recommendations):
        """
        recommendations: list of dicts, sorted by ml_prob descending.
        [{'code': '...', 'name': '...', 'ml_prob': 85.0, 'price': 10000}]
        """
        current_date = self._get_current_date()
        print(f"\n[Trader] Executing Buy Logic for {len(recommendations)} candidates...")
        
        # Update days held for existing stocks
        if self.state.get('last_update') != current_date:
            last_dt_str = self.state.get('last_update')
            days_to_add = 1
            if last_dt_str:
                try:
                    # Handle full timestamp if present
                    last_only_date = last_dt_str.split(' ')[0]
                    last_dt = datetime.strptime(last_only_date, '%Y-%m-%d')
                    curr_dt = datetime.strptime(current_date, '%Y-%m-%d')
                    days_gap = (curr_dt - last_dt).days
                    if days_gap > 0:
                        days_to_add = days_gap
                except Exception as e:
                    print(f"Error parsing date: {e}")
                    pass
            
            print(f"  [System] New day detected ({current_date}). Incrementing days_held by {days_to_add}.")
            for code in self.state['holdings']:
                self.state['holdings'][code]['days_held'] += days_to_add
            self.state['last_update'] = current_date
            
        buy_count = 0
        for rec in recommendations:
            code = rec.get('code')
            if code in self.state['holdings']:
                continue # Already holding
                
            prob = float(rec.get('ml_prob', 0))
            if prob < 60.0:
                continue # Only buy strong signals
                
            price = float(rec.get('price', 0))
            if price <= 0:
                continue
                
            # Position sizing
            max_alloc = self.INITIAL_CASH * self.MAX_ALLOCATION_PER_STOCK
            alloc = min(max_alloc, self.state['cash'])
            
            qty = int(alloc // price)
            if qty > 0:
                buy_vol = qty * price
                fee = buy_vol * self.FEE_BUY
                total_cost = buy_vol + fee
                
                if self.state['cash'] >= total_cost:
                    self.state['cash'] -= total_cost
                    self.state['holdings'][code] = {
                        'qty': qty, 
                        'avg_price': price, 
                        'buy_date': current_date, 
                        'days_held': 0, 
                        'name': rec.get('name', code),
                        'target_prob': prob
                    }
                    print(f"  [Action] BUY {code} ({rec.get('name')}) - {qty} shares @ {price:,.0f} KRW (ML Prob: {prob:.1f}%)")
                    self.state['trade_log'].append({
                        'date': current_date + " " + datetime.utcnow().strftime('%H:%M:%S'), 
                        'type': 'BUY', 
                        'code': code, 
                        'name': rec.get('name', code),
                        'qty': qty, 
                        'price': price, 
                        'prob': prob,
                        'reason': 'ML Strong Buy Signal'
                    })
                    buy_count += 1
                    
        if buy_count == 0:
            print("  [Result] No new buys executed (Threshold or Cash constraint).")
            
        self._save_state()
