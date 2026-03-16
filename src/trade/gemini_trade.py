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

    def _load_state(self):
        if os.path.exists(self.portfolio_file):
            try:
                with open(self.portfolio_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading gemini portfolio: {e}")
                
        # Initialize defaults if not exists
        return {
            'cash': self.INITIAL_CASH,
            'holdings': {}, # code: {qty, avg_price, buy_date, days_held, name, target_prob}
            'trade_log': [],
            'last_update': '',
            'algo_version': 'v_unknown',
            'market_regime': 'NEUTRAL', # BULL, BEAR, NEUTRAL
            'benchmark_base': {} # {'KOSPI': 2500, ...}
        }
        
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
                    
        for c in codes_to_sell:
            del self.state['holdings'][c]
            
        self._save_state()
        
    def execute_buys(self, recommendations):
        """
        recommendations: list of dicts, sorted by ml_prob descending.
        [{'code': '...', 'name': '...', 'ml_prob': 85.0, 'price': 10000}]
        """
        current_date = self._get_current_date()
        
        # Update days held for existing stocks
        if self.state.get('last_update') != current_date:
            last_dt_str = self.state.get('last_update')
            days_to_add = 1
            if last_dt_str:
                try:
                    last_dt = datetime.strptime(last_dt_str, '%Y-%m-%d')
                    curr_dt = datetime.strptime(current_date, '%Y-%m-%d')
                    days_gap = (curr_dt - last_dt).days
                    if days_gap > 0:
                        days_to_add = days_gap
                except Exception as e:
                    print(f"Error parsing date: {e}")
                    pass
            
            for code in self.state['holdings']:
                self.state['holdings'][code]['days_held'] += days_to_add
            self.state['last_update'] = current_date
            
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
                    
        self._save_state()
