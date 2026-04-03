import json
import os
import datetime

PORTFOLIO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'virtual_portfolio.json')

class VirtualPortfolioManager:
    def __init__(self):
        self.filepath = PORTFOLIO_FILE
        # Create data dir if not exists
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        self.init_portfolio()

    def init_portfolio(self):
        if not os.path.exists(self.filepath):
            # empty port schema
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=2)

    def get_portfolio(self):
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}

    def save_portfolio(self, data):
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[VirtualPortfolio] Save Error: {e}")
            return False

    def buy_stock(self, code, name, price, quantity=10): # Defaults to 10 shares for simulation
        port = self.get_portfolio()
        # Initialize or add to existing
        if code in port:
            # Average down/up calculation
            old_qty = port[code].get('quantity', 0)
            old_avg = port[code].get('average_buy_price', 0.0)
            new_qty = old_qty + quantity
            new_avg = ((old_qty * old_avg) + (quantity * price)) / new_qty
            
            port[code]['quantity'] = new_qty
            port[code]['average_buy_price'] = new_avg
            port[code]['last_updated'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        else:
            port[code] = {
                'name': name,
                'quantity': quantity,
                'average_buy_price': float(price),
                'buy_date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'last_updated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        
        self.save_portfolio(port)
        return port[code]

    def sell_stock(self, code, sell_qty=None):
        """
        sell_qty가 None이거나 quantity와 같거나 크면 전량 매도.
        """
        port = self.get_portfolio()
        if code not in port:
            return None
            
        current_qty = port[code].get('quantity', 0)
        
        # Calculate PnL (Just for return info, actual tracking via external)
        # We don't have current price here unless passed, so we just do qty management
        
        if sell_qty is None or sell_qty >= current_qty:
            sold_info = port.pop(code)
            self.save_portfolio(port)
            return {"action": "SELL_ALL", "qty_sold": current_qty, "remaining_qty": 0}
        else:
            port[code]['quantity'] = current_qty - sell_qty
            port[code]['last_updated'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.save_portfolio(port)
            return {"action": "SELL_HALF", "qty_sold": sell_qty, "remaining_qty": port[code]['quantity']}
