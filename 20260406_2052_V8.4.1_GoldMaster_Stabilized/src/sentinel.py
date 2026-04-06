import os
import json
import google.generativeai as genai
from datetime import datetime

class SentinelV:
    """
    Technical Analysis Sentinel (Updated V9.0)
    Analyzes stock data to generate BUY/SELL signals based on reinforced logic.
    """
    def __init__(self):
        self.history_file = 'data/sentinel_history.json'
        self.history = self._load_history()

    def _load_history(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def analyze_stock(self, stock, threshold=None):
        """
        Analyzes a single stock and returns (signal, reason).
        Signal: "BUY_STRONG", "BUY", "SELL", "SELL_STRONG", or "None"
        threshold: The dynamic post count criteria used for this run (e.g., 40, 60, 100).
        """
        signal = "None"
        reason = ""

        # Default fallback if threshold not provided
        if threshold is None:
            # Simple time-based fallback (KST)
            current_hour = (datetime.utcnow().hour + 9) % 24
            if 9 <= current_hour < 12: threshold = 40
            elif 12 <= current_hour < 14: threshold = 60
            elif 14 <= current_hour < 24: threshold = 100
            else: threshold = 10


        try:
            name = stock.get('name', '')
            price = float(stock.get('price', 0))
            change_rate = float(str(stock.get('change_rate', '0')).replace('%', ''))
            
            # Foreign Rate Parsing
            fr_str = str(stock.get('foreign_rate', '0')).replace('%', '')
            foreign_rate = float(fr_str) if fr_str else 0.0
            
            pfr_str = str(stock.get('prev_foreign_rate', '0')).replace('%', '')
            prev_foreign_rate = float(pfr_str) if pfr_str else 0.0
            
            consecutive = int(stock.get('consecutive_days', 0))
            posts_count = int(stock.get('recent_posts_count', 0))
            
            # Volume Check (Simple heuristic if avg unavailable)
            # If 'volume' is a raw number.
            volume = float(stock.get('volume', 0))

            # Logic Reinforcement
            
            # 1. BUY_STRONG: Proven Trend + Institutional/Foreign Interest
            # - Consecutive 3+ days
            # - Foreign ownership increasing
            # - Positive price action
            # - High Community Interest (At least meeting the dashboard threshold)
            if consecutive >= 3 and foreign_rate > prev_foreign_rate and change_rate > 0 and posts_count >= threshold:
                signal = "BUY_STRONG"
                reason = f"3일 연속+외인확대({foreign_rate}%)+Buzz({posts_count})"

            # 2. BUY: Volume Breakout or Sudden Spike
            elif change_rate >= 15.0:
                 signal = "BUY"
                 reason = f"급등세 포착 (+{change_rate}%)"
            elif change_rate > 5.0 and foreign_rate > prev_foreign_rate + 0.1 and posts_count >= (threshold * 1.5):
                 signal = "BUY"
                 reason = f"상승세+외인수급+강한토론({posts_count})"

            # 3. SELL: Foreign Exodus or Trend Break
            elif foreign_rate < prev_foreign_rate - 0.5:
                signal = "SELL"
                reason = f"외인 대량 이탈 ({prev_foreign_rate}% -> {foreign_rate}%)"
            elif change_rate < -5.0 and foreign_rate < prev_foreign_rate and posts_count >= threshold:
                signal = "SELL"
                reason = f"하락세 전환 + 외인 매도 동반"

        except Exception as e:
            # print(f"Sentinel Analysis Error for {stock.get('name')}: {e}")
            pass

        return signal, reason

class GeminiAgent:
    """
    AI Insight Agent using Google Gemini Model.
    Target: gemini-2.5-flash-lite
    """
    def __init__(self):
        self.api_key = os.environ.get('GOOGLE_API_KEY')
        if not self.api_key:
            print("[GeminiAgent] Warning: GOOGLE_API_KEY not found.")
            self.model = None
            return

        genai.configure(api_key=self.api_key)
        # Using the specific model ID requested by verification
        self.model = genai.GenerativeModel('gemini-2.5-flash-lite')

    def generate_risk_assessment(self, symbol, signal_type, technical_reason, keywords, summary):
        """Generates a short risk assessment for SELL signals."""
        if not self.model: return "AI Not Configured"

        prompt = f"""
        Analyze the SELL signal for stock '{symbol}'.
        Signal: {signal_type}
        Reason: {technical_reason}
        Recent Buzz Keywords: {keywords}
        Community Summary: {summary}

        Provide a 1-sentence risk assessment relative to the sell signal.
        Start with "Gemini 2.5 Opinion: "
        """
        try:
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"Analysis Failed: {str(e)}"

    def generate_trading_guide(self, all_data, sentinel_signals=None):
        """
        Generates a comprehensive trading guide.
        Integrates Sentinel-V signals if provided.
        """
        if not self.model: return "AI Not Configured"

        # 1. Prepare Market Data Summary
        sorted_stocks = sorted(all_data, key=lambda x: float(str(x.get('change_rate','0')).replace('%','')), reverse=True)[:10]
        market_context = ""
        for s in sorted_stocks:
            market_context += f"- {s.get('name')}: {s.get('price')} ({s.get('change_rate')}), Keywords: {s.get('top_keywords')}\n"

        # 2. Sentinel Signals Context
        signal_context = ""
        if sentinel_signals:
            signal_context = "[Sentinel-V Detected Signals]\n"
            for s in sentinel_signals:
                signal_context += f"- {s['name']}: {s['signal']} ({s['reason']})\n"
        
        # 3. Load Research/News Data
        research_context = ""
        try:
            if os.path.exists('data/latest_research.json'):
                with open('data/latest_research.json', 'r', encoding='utf-8') as f:
                    research_data = json.load(f)
                    items = research_data.get('company', {}).get('items', [])[:5] + research_data.get('invest', {}).get('items', [])[:3]
                    for item in items:
                        research_context += f"- [Report] {item.get('title')} (Date: {item.get('date')}) -> Trend: {item.get('body_summary', '')[:50]}...\n"
        except:
            pass

        # 4. Construct Prompt
        prompt = f"""
        Role: Senior Stock Analyst (using Gemini 2.5 Flash Lite)
        Task: Write a concise "Trading Guide" (매매 가이드).
        
        Data Sources:
        {market_context}
        
        {signal_context}
        
        [Recent Reports]
        {research_context}
        
        Requirements:
        1. **Signal Validation**: If there are Sentinel-V signals, explicitly analyze them. Agree or Disagree based on favorable/unfavorable news or buzz.
        2. **Top Picks**: Select 3 stocks (prioritize those with Sentinel Buy signals OR strong News support).
        3. Format:
           📌 **[Stock Name]** | Action: [Buy/Hold/Watch]
           → 💡 Basis: [Technical + Sentinel Signal + News]. *Cite sources.*
           → 🎯 Strategy: [Entry/Exit suggestion]
        
        4. Tone: Professional, objective, and actionable.
        5. Language: Korean.
        """
        
        try:
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"Trading Guide Generation Failed: {str(e)}"
