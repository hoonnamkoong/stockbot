import sys
import os
import json
import pandas as pd
from datetime import datetime
from src.core.config import SENTINEL_V, MESSAGES
from src.features.gemini_agent import GeminiAgent
from src.telegram_manager import TelegramManager

# [V8.9.9.19] scripts 디렉토리를 path에 추가하여 scraper 임포트 해결
sys.path.append(os.path.join(os.getcwd(), 'scripts'))
import scraper 

from src.analyzer_5days import safe_float, safe_int, get_recent_working_days, load_daily_snapshots

class SentinelV:
    """
    Sentinel-V Advisory System.
    Monitors market for Buy Signals and manages Active Recommendations (Advisory).
    Includes Anti-FOMO Logic (Overheat Prevention).
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

    def check_historical_overheat(self, code, current_price, snapshots):
        """
        Anti-FOMO: Checks if stock rose > 50% in last 5 days.
        """
        if not snapshots: return False, 0.0
        
        # Find oldest available price in snapshots
        dates = sorted(snapshots.keys())
        oldest_price = 0
        
        for d in dates:
            df = snapshots[d]
            # code matching (ensure format)
            # Ensure code is string and zero-padded
            code_str = str(code).zfill(6)
            # Assuming df['code'] might be int or string
            df['code'] = df['code'].astype(str).str.zfill(6)
            
            row = df[df['code'] == code_str]
            if not row.empty:
                oldest_price = safe_int(row.iloc[0]['price'])
                break # Found oldest available price in the window
                
        if oldest_price > 0:
            cumulative_return = (current_price - oldest_price) / oldest_price * 100
            if cumulative_return > 50.0:
                return True, cumulative_return
                
        return False, 0.0

    def analyze_stock(self, stock, snapshots=None):
        """
        Applies Sentinel-V Advisory Logic + Anti-FOMO.
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
        if foreign_rate > 0 and prev_foreign_rate > 0:
            # Divergence Check (Strict)
            if foreign_rate < prev_foreign_rate:
                 return "PASS", f"외국인 이탈 ({prev_foreign_rate}->{foreign_rate}%)"

        # 3. Buzz Filter
        is_buzzing = False
        if posts_count >= self.config['SPARK_POSTS_MIN']: # 400
            is_buzzing = True
            
        if not is_buzzing:
            return "PASS", "게시물 부족"
            
        # 4. Anti-FOMO (Overheat Check)
        if snapshots:
            is_overheated, cum_return = self.check_historical_overheat(stock['code'], current_price, snapshots)
            if is_overheated:
                return "PASS", f"이격도 과열 (5일 +{cum_return:.1f}%)"

        # PQI Check
        pqi = self.calculate_pqi(stock.get('latest_posts', []))
        if pqi < self.config['PQI_MIN']:
            return "PASS_LOW_QUALITY", f"Low PQI: {pqi:.2f}"

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
        """Advisory Monitor: Profit Taking / Stop Loss"""
        recs = self.load_recommendations()
        if not recs: return
        
        updated_recs = {}
        stock_map = {s['code']: s for s in trending_stocks}
        
        for code, rec in recs.items():
            current_data = stock_map.get(code)
            
            if current_data:
                current_price = current_data['price']
                change_rate = safe_float(current_data['change_rate'])
                
                # Update Peak Price
                if current_price > rec['peak_price']:
                    rec['peak_price'] = current_price
                    
                buy_price = rec['recommended_price']
                profit_rate = (current_price - buy_price) / buy_price * 100
                drop_from_peak = (rec['peak_price'] - current_price) / rec['peak_price'] * 100
                
                if profit_rate > rec.get('highest_profit_rate', -99):
                    rec['highest_profit_rate'] = profit_rate
                
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
            
            updated_recs[code] = rec
            
        self.save_recommendations(updated_recs)

    def run(self):
        """Main Execution Flow"""
        print("=== Sentinel-V Advisory System Triggered ===")
        
        # 0. Load History for Anti-FOMO
        print("[Sentinel-V] Loading historical data for Anti-FOMO check...")
        working_days = get_recent_working_days(6) 
        snapshots = load_daily_snapshots(working_days[1:]) # Past 5 days
        
        # 1. Fetch Basic Trend List
        trending_stocks = scraper.get_top_trending_stocks('KOSDAQ')
        
        # Enrich Data
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
        
        # 2. Monitor Recommendations
        self.monitor_recommendations(enriched_stocks)
        
        # 3. New Opportunities
        action_taken = False
        recs = self.load_recommendations()
        
        for stock in enriched_stocks[:20]: 
            code = stock['code']
            if code in recs: continue 
            
            # Analyze with Snapshots
            signal, reason = self.analyze_stock(stock, snapshots)
            
            print(f"[{stock['name']}] Signal: {signal} | {reason}")
            
            if signal == "BUY_STRONG":
                action_taken = True
                
                recs[code] = {
                    "name": stock['name'],
                    "recommended_date": datetime.now().strftime('%Y-%m-%d'),
                    "recommended_price": stock['price'],
                    "peak_price": stock['price'],
                    "highest_profit_rate": 0.0,
                    "status": "WATCHING"
                }
                self.save_recommendations(recs)
                
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
