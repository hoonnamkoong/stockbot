
import sys
import os
import json
import pandas as pd
from datetime import datetime
from src.core.config import SENTINEL_V, MESSAGES
from src.features.gemini_agent import GeminiAgent
from src.telegram_manager import TelegramManager
import scraper # Import existing scraper for data fetching
from src.analyzer_5days import safe_float, safe_int

class SentinelV:
    """
    Sentinel-V Advisory System.
    Monitors market for Buy Signals and manages Active Recommendations (Advisory).
    """
    def __init__(self):
        self.gemini = GeminiAgent()
        self.tg = TelegramManager()
        self.config = SENTINEL_V
        self.rec_file = 'data/active_recommendations.json'
        
    def load_recommendations(self):
        """Loads valid active recommendations."""
        if not os.path.exists(self.rec_file):
            return {}
        try:
            with open(self.rec_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[Sentinel-V] Error loading recommendations: {e}")
            return {}

    def save_recommendations(self, data):
        """Saves current recommendations."""
        try:
            with open(self.rec_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Sentinel-V] Error saving recommendations: {e}")

    def calculate_pqi(self, posts):
        """PQI = (Likes / Views) * 100"""
        if not posts: return 0
        total_views = sum(int(p.get('views', 0).replace(',', '')) for p in posts if str(p.get('views', '')).replace(',', '').isdigit())
        total_likes = sum(int(p.get('likes', 0)) for p in posts if str(p.get('likes', '0')).isdigit())
        
        if total_views == 0: return 0
        return (total_likes / total_views) * 100

    def analyze_stock(self, stock):
        """
        Applies Sentinel-V Advisory Logic to a single stock.
        Returns: 'BUY_STRONG', 'PASS', 'WARN_OVERHEAT'
        """
        # Data Extraction
        posts_count = stock.get('recent_posts_count', 0)
        current_price = stock.get('price', 0)
        change_rate = safe_float(stock.get('change_rate'))
        foreign_rate = safe_float(stock.get('foreign_rate', '0'))
        prev_foreign_rate = safe_float(stock.get('prev_foreign_rate', '0.0'))
        
        # 1. Technical Filter (Trend)
        if change_rate < -3.0:
            return "PASS", f"하락 추세 강함 ({change_rate}%)"
            
        # 2. Supply Filter (Foreigner)
        # Foreigner buying is a strong signal, but if small cap with 0% foreign, skip strict check
        if foreign_rate > 0 and prev_foreign_rate > 0:
            if foreign_rate < prev_foreign_rate:
                 return "PASS", f"외국인 이탈 ({prev_foreign_rate}->{foreign_rate}%)"

        # 3. Buzz Filter
        # Spark Check: High Volume or Growth (Growth requires yesterday data, assume High Volume for now)
        is_buzzing = False
        if posts_count >= self.config['SPARK_POSTS_MIN']: # 400
            is_buzzing = True
            
        if not is_buzzing:
            return "PASS", "게시물 부족"
            
        # PQI Check (Quality)
        pqi = self.calculate_pqi(stock.get('latest_posts', []))
        if pqi < self.config['PQI_MIN']:
            return "PASS_LOW_QUALITY", f"Low PQI: {pqi:.2f}"

        # 4. Overheat Warning
        if change_rate > 20.0:
            return "WARN_OVERHEAT", f"단기 급등 과열 ({change_rate}%)"

        # 5. Agentic Check (Gemini)
        keywords = [p['title'] for p in stock.get('latest_posts', [])[:5]]
        
        print(f"[Sentinel-V] Requesting Gemini for {stock['name']}...")
        validation = self.gemini.cross_validate(stock['name'], keywords)
        
        if validation['status'] == 'APPROVED':
            msg = f"Gemini Approved: {validation['reason']}"
            if foreign_rate > prev_foreign_rate:
                 msg += f" (외인 {prev_foreign_rate}->{foreign_rate}%)"
            return "BUY_STRONG", msg
        
        return "PASS", "Gemini did not approve"

    def monitor_recommendations(self, trending_stocks):
        """
        Monitors active recommendations and provides Sell/Hold advice.
        """
        recs = self.load_recommendations()
        if not recs: return
        
        updated_recs = {}
        stock_map = {s['code']: s for s in trending_stocks}
        
        for code, rec in recs.items():
            # If stock is in today's trend list, update it
            current_data = stock_map.get(code)
            
            if current_data:
                current_price = current_data['price']
                change_rate = safe_float(current_data['change_rate'])
                
                # Update Peak Price
                if current_price > rec['peak_price']:
                    rec['peak_price'] = current_price
                    
                # Calculate Returns
                buy_price = rec['recommended_price']
                profit_rate = (current_price - buy_price) / buy_price * 100
                drop_from_peak = (rec['peak_price'] - current_price) / rec['peak_price'] * 100
                
                # Update Max Profit recorded
                if profit_rate > rec.get('highest_profit_rate', -99):
                    rec['highest_profit_rate'] = profit_rate
                
                # Advisory Logic
                advice = None
                
                # 1. Stop Loss (Trailing Stop)
                if drop_from_peak >= 4.0 and profit_rate > 0:
                    advice = f"📉 [Trailing Stop] 고점 대비 -{drop_from_peak:.1f}% 하락. 이익 실현 권장."
                elif profit_rate < -5.0:
                     advice = f"💧 [Stop Loss] 진입가 대비 -{abs(profit_rate):.1f}% 하락. 손절 검토."
                     
                # 2. Profit Taking (Overheat)
                posts = current_data.get('recent_posts_count', 0)
                if posts >= 800 and change_rate < 29.0:
                    advice = f"🔥 [Overheat] 게시물 폭발({posts}건). 상한가가 아니라면 분할 매도 권장."
                    
                if advice:
                    msg = f"🔔 <b>[Sentinel-V] Advisory Alert</b>\n\nStock: {rec['name']} ({code})\nAdvice: {advice}\nProfit: {profit_rate:.1f}%"
                    self.tg.send_message(msg)
                    # Once advised to exit, maybe remove? Or keep until sold?
                    # For advisory, we keep it but mark advised
            
            # Keep in list (User decides when to stop tracking, or auto-expire after N days)
            updated_recs[code] = rec
            
        self.save_recommendations(updated_recs)

    def run(self):
        """Main Execution Flow"""
        print("=== Sentinel-V Advisory System Triggered ===")
        
        # 1. Fetch Basic Trend List
        trending_stocks = scraper.get_top_trending_stocks('KOSDAQ')
        
        # Enrich Data (CRITICAL: Get Foreign Rate & Prev Close)
        enriched_stocks = []
        for stock in trending_stocks:
             try:
                 details = scraper.get_stock_details(stock['code'])
                 stock.update(details)
                 stats = scraper.get_discussion_stats(stock['code'])
                 stock.update(stats)
                 enriched_stocks.append(stock)
             except Exception as e:
                 print(f"Error enriching {stock['name']}: {e}")
                 continue
        
        # 2. Monitor Existing Recommendations (AS)
        self.monitor_recommendations(enriched_stocks)
        
        # 3. Scan for New Opportunities
        action_taken = False
        recs = self.load_recommendations()
        
        for stock in enriched_stocks[:20]: # Check Top 20
            code = stock['code']
            if code in recs: continue # Already tracking
            
            # Analyze
            signal, reason = self.analyze_stock(stock)
            
            print(f"[{stock['name']}] Signal: {signal} | {reason}")
            
            if signal == "BUY_STRONG":
                action_taken = True
                
                # Register Recommendation
                recs[code] = {
                    "name": stock['name'],
                    "recommended_date": datetime.now().strftime('%Y-%m-%d'),
                    "recommended_price": stock['price'],
                    "peak_price": stock['price'],
                    "highest_profit_rate": 0.0,
                    "status": "WATCHING"
                }
                self.save_recommendations(recs)
                
                # Notify
                msg = MESSAGES['BUY_SIGNAL'].format(
                    name=stock['name'],
                    code=stock['code'],
                    reason=reason,
                    ai_comment=reason, 
                    trigger_val=stock['recent_posts_count']
                )
                self.tg.send_message(msg)

        if not action_taken:
            print("[Sentinel-V] No new buy signals.")

if __name__ == "__main__":
    bot = SentinelV()
    bot.run()
