import sys
import os
import json
import pandas as pd
from datetime import datetime
from src.core.config import SENTINEL_V, MESSAGES
from src.features.gemini_agent import GeminiAgent
from src.telegram_manager import TelegramManager
import scraper # Import existing scraper for data fetching

class SentinelV:
    """
    Sentinel-V Core Algorithm Implementation.
    Manages Spark Entry, Safety Lock, and Profit Run phases.
    """
    def __init__(self):
        self.gemini = GeminiAgent()
        self.tg = TelegramManager()
        self.config = SENTINEL_V
        
    def load_yesterday_data(self):
        """Loads yesterday's post counts for 'Spark Check'."""
        # Logic to find the last valid JSON report from 'data/'
        # For MVP, we will assume 0 if not found, or implement simple file lookup
        return {} # Placeholder: Needs robust file loading logic

    def calculate_pqi(self, posts):
        """PQI = (Likes / Views) * 100"""
        if not posts: return 0
        total_views = sum(int(p.get('views', 0).replace(',', '')) for p in posts if str(p.get('views', '')).replace(',', '').isdigit())
        total_likes = sum(int(p.get('likes', 0)) for p in posts if str(p.get('likes', '0')).isdigit())
        
        if total_views == 0: return 0
        return (total_likes / total_views) * 100

    def analyze_stock(self, stock):
        """
        Applies Sentinel-V Logic to a single stock.
        Returns: 'BUY_STRONG', 'SELL_HALF', 'SELL_ALL', 'HOLD', 'PASS'
        """
        # Data Extraction
        posts_count = stock.get('recent_posts_count', 0)
        
        # 1. Exit Logic (If we held it - requires state management, skip for now or assume monitoring)
        # For this MVP, we focus on ENTRY signals and stateless EXIT (e.g. just notifying if conditions met)
        
        if posts_count >= self.config['SAFETY_LOCK_POSTS']:
             return "SELL_HALF_PROFIT", f"Posts reached {posts_count} (Zone > {self.config['SAFETY_LOCK_POSTS']})"

        # 2. Entry Logic
        # Spark Check
        if posts_count < self.config['SPARK_POSTS_MIN']:
            return "PASS", "Too few posts"
            
        # PQI Check
        pqi = self.calculate_pqi(stock.get('latest_posts', []))
        if pqi < self.config['PQI_MIN']:
            return "PASS_LOW_QUALITY", f"Low PQI: {pqi:.2f}"

        # Agentic Check (Gemini)
        # Assuming 'top_keywords' or similar is extracted from posts titles
        keywords = [p['title'] for p in stock.get('latest_posts', [])[:5]]
        
        print(f"[Sentinel-V] Requesting Gemini for {stock['name']}...")
        validation = self.gemini.cross_validate(stock['name'], keywords)
        
        if validation['status'] == 'APPROVED':
            return "BUY_STRONG", f"Gemini Approved: {validation['reason']}"
        
        return "PASS", "Gemini did not approve"

    def run(self):
        """Main Execution Flow"""
        print("=== Sentinel-V Triggered ===")
        
        # 1. Fetch Real-time Data (Market: KOSDAQ as per spec)
        # Using scraper's function directly
        trending_stocks = scraper.get_top_trending_stocks('KOSDAQ')
        
        action_taken = False
        scan_results = []
        
        for stock in trending_stocks[:20]: # Check Top 20
            # Enrich with discussion stats
            stats = scraper.get_discussion_stats(stock['code'])
            stock.update(stats)
            
            # Analyze
            signal, reason = self.analyze_stock(stock)
            
            print(f"[{stock['name']}] Signal: {signal} | {reason}")
            scan_results.append(f"{stock['name']} ({signal})")
            
            if "BUY" in signal or "SELL" in signal:
                action_taken = True
                # Notify
                msg_template = MESSAGES['BUY_SIGNAL'] if "BUY" in signal else MESSAGES['SELL_SIGNAL']
                msg = msg_template.format(
                    name=stock['name'],
                    code=stock['code'],
                    reason=reason,
                    ai_comment=reason, # reusing reason for now
                    trigger_val=stock['recent_posts_count']
                )
                self.tg.send_message(msg)
        
        # Silent Heartbeat -> Expert Briefing (User Request: Korean Analysis)
        if not action_taken:
            print("[Sentinel-V] No signals found. Generating Expert Briefing...")
            
            # Prepare data for Gemini (Needs 'top_keywords')
            analysis_candidates = []
            for stock in trending_stocks[:10]:
                # Simple keyword extraction from titles if not present
                if 'top_keywords' not in stock:
                    titles = [p['title'] for p in stock.get('latest_posts', [])]
                    stock['top_keywords'] = ", ".join(titles[:3]) if titles else "이슈 없음"
                analysis_candidates.append(stock)

            guide = self.gemini.generate_trading_guide(analysis_candidates)
            
            timestamp = datetime.now().strftime('%H:%M')
            summary = f"🤖 <b>[Sentinel-V] 시장 감시 리포트 ({timestamp})</b>\n\n"
            summary += f"특이 종목이 포착되지 않았으나, 현재 시장 흐름은 다음과 같습니다:\n\n"
            summary += guide
            
            self.tg.send_message(summary)



if __name__ == "__main__":
    bot = SentinelV()
    bot.run()
