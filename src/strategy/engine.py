import json
import datetime

class StrategyEngine:
    """
    Pure Logic Engine for Stock Scoring and Signal Generation.
    NO external API calls (KIS, Google, etc.) allowed here.
    """
    def __init__(self, config=None):
        self.config = config or {
            'weights': {'trend': 0.5, 'supply': 0.5},
            'thresholds': {'buy_strong': 30, 'buy': 20, 'sell': -3.0}
        }

    def calculate_score(self, stock_data):
        """
        Calculates a score based on trend and supply.
        stock_data: dict containing 'change_rate', 'foreign_rate', etc.
        """
        trend_score = 0
        try:
            p_change = float(str(stock_data.get('change_rate', '0')).replace('%', ''))
        except:
            p_change = 0.0
            
        # Trend Logic
        if p_change > 2.0: trend_score += 20
        if p_change > 5.0: trend_score += 10
        
        supply_score = 0
        try:
            frg = float(str(stock_data.get('foreign_rate', '0')).replace('%', ''))
            if frg > 0: supply_score += 10
            if frg > 5: supply_score += 10
        except:
            pass
            
        total_score = trend_score + supply_score
        return total_score, p_change

    def get_signal(self, score, p_change, in_portfolio=False, profit_rate=0.0):
        """
        Determines the signal based on score and portfolio state.
        """
        signal = "HOLD"
        confidence = "LOW"
        
        if score >= self.config['thresholds']['buy_strong']:
            signal = "BUY_STRONG"
            confidence = "HIGH"
        elif score >= self.config['thresholds']['buy']:
            signal = "BUY"
            confidence = "MEDIUM"
        elif p_change < self.config['thresholds']['sell']:
            signal = "SELL"
            confidence = "MEDIUM"
            
        # Add dynamic portfolio logic (Ride the winner, Stop loss)
        if in_portfolio:
            if profit_rate >= 10.0:
                if p_change > 2.0 or signal == "BUY_STRONG":
                    signal = "HOLD" # Ride winner
                else:
                    signal = "SELL" # Profit take
            elif profit_rate <= -7.0:
                signal = "SELL" # Stop loss
                
        return signal, confidence
