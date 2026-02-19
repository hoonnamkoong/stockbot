
import os
import sys
import json
import time
import requests
import datetime
import google.generativeai as genai
from collections import Counter
import re

# Add parent directory to path to allow imports from src/trade
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

try:
    from trade.auth import get_access_token, load_env
except ImportError:
    # Fallback if running from root
    from src.trade.auth import get_access_token, load_env

# --- 1. SentinelV Logic (Extracted from scraper.py) ---
class SentinelV:
    def __init__(self):
        self.weights = {
            'trend': 0.4,
            'supply': 0.3, # Foreign/Inst
            'buzz': 0.3    # Search/SNS
        }
        
    def analyze_stock(self, stock, threshold=None):
        """
        Calculates a proprietary score (0-100) and returns a Signal.
        """
        # 1. Trend Score (40%)
        trend_score = 0
        try:
            p_change = float(str(stock.get('change_rate', '0')).replace('%', ''))
        except:
            p_change = 0.0
        
        # V9.0: Enhanced Trend Logic
        if p_change > 2.0: trend_score += 20
        if p_change > 5.0: trend_score += 10 # Strong momentum
        if p_change > 15.0: trend_score += 10 # Very strong
        
        # Close near high? (Using Price as Close)
        close = float(stock.get('price', 0))
        # We don't have 'high' in basic scraper data usually, so skip high/close check or use heuristics
        # if high > 0 and close >= high * 0.95: trend_score += 10 
             
        # 2. Supply Score (30%)
        supply_score = 0
        frg_rate = str(stock.get('foreign_rate', '0')).replace('%', '')
        try:
            frg = float(frg_rate)
            if frg > 0: supply_score += 10
            if frg > 5: supply_score += 10
        except:
             pass
             
        # 3. Buzz Score (30%)
        buzz_score = 0
        # In this scraper context, 'Buzz' is often derived from rank or keywords
        # Top 10 Volume = High Buzz
        rec_posts = int(stock.get('recent_posts_count', 0))
        if rec_posts > 50: buzz_score += 10
        if rec_posts > 100: buzz_score += 10
        
        total_score = trend_score + supply_score + buzz_score
        
        # Determine Signal
        signal = "HOLD"
        confidence = "LOW"
        
        # [Adjusted Logic for Strategy]
        if total_score >= 60:
            signal = "BUY_STRONG"
            confidence = "HIGH"
        elif total_score >= 40:
            signal = "BUY"
            confidence = "MEDIUM"
        elif p_change < -3.0: # Simple Sell Trigger for now
            signal = "SELL"
            confidence = "MEDIUM"
            
        return {
            'signal': signal,
            'score': total_score,
            'confidence': confidence,
            'factors': {
                'trend': trend_score,
                'supply': supply_score,
                'buzz': buzz_score
            }
        }

# --- 2. Gemini Agent Logic (Extracted from scraper.py) ---
class GeminiAgent:
    def __init__(self):
        load_env()
        self.api_key = os.environ.get('GOOGLE_API_KEY')
        if not self.api_key:
             # Try fallback
             self.api_key = os.environ.get('GEMINI_KEY')
             
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel('gemini-2.5-flash-lite')
        else:
            self.model = None
            print("[GeminiAgent] Warning: No API Key found.")

    def generate_trading_guide(self, market_context, sentinel_signals):
        if not self.model:
            return "Gemini API Key missing."
            
        msg_date = datetime.datetime.now().strftime('%Y-%m-%d')
        prompt = f"""
        Role: Senior Stock Analyst (using Gemini 2.5 Flash Lite)
        Task: Write a concise "Trading Guide" (매매 가이드).
        Current Date: {msg_date}
        
        Data Sources:
        1. Market Context: {market_context}
        2. Sentinel Signals (Top Picks): {json.dumps(sentinel_signals, ensure_ascii=False, indent=2)}
        
        Requirement:
        - Analyze the top picks based on their signals and scores.
        - Provide actionable advice (Buy/Watch/Sell) referencing their specific strengths (Trend, Foreign, etc).
        - Keep it brief (bullet points).
        - Tone: Professional, objective.
        """
        
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"Gemini Error: {e}"

# --- 3. Strategy Advisor (The Coordinator) ---
class StrategyAdvisor:
    def __init__(self):
        self.sentinel = SentinelV()
        self.gemini = GeminiAgent()
        self.portfolio = self.fetch_portfolio()
        
    def fetch_portfolio(self):
        """
        Fetches current holdings using KIS API logic (from trade/balance.py).
        Returns a dict: {'005930': {'qty': 10, 'avg_price': 70000}, ...}
        """
        print("[Advisor] Fetching Portfolio...")
        holdings = {}
        
        # Reuse logic from trade/balance.py (simplified)
        access_token = get_access_token()
        if not access_token: return {}
        
        load_env()
        app_key = os.environ.get("KIS_APP_KEY")
        app_secret = os.environ.get("KIS_APP_SECRET")
        account_no_full = os.environ.get("KIS_ACCOUNT_NO")
        base_url = os.environ.get("KIS_BASE_URL")
        
        if not (account_no_full and base_url): return {}

        clean_acc = account_no_full.replace('-', '')
        cano = clean_acc[:8]
        acnt_prdt_cd = clean_acc[8:]
        
        url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {access_token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": "VTTC8434R",
            "custtype": "P"
        }
        params = {
            "CANO": cano, "ACNT_PRDT_CD": acnt_prdt_cd, "AFHR_FLPR_YN": "N", "OFL_YN": "N",
            "INQR_DVSN": "02", "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N", 
            "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            if res.status_code == 200 and res.json()['rt_cd'] == '0':
                items = res.json().get('output1', [])
                for item in items:
                    code = item.get('pdno') # Product Number (Code)
                    qty = int(item.get('hldg_qty'))
                    avg_price = float(item.get('pchs_avg_pric'))
                    name = item.get('prdt_name')
                    
                    if qty > 0:
                        holdings[code] = {
                            'name': name,
                            'qty': qty,
                            'avg_price': avg_price,
                            'current_price': float(item.get('prpr')),
                            'profit_rate': float(item.get('evlu_pfls_rt'))
                        }
        except Exception as e:
            print(f"[Advisor] Portfolio Fetch Error: {e}")
            
        print(f"[Advisor] Portfolio loaded: {len(holdings)} items")
        return holdings

    def fetch_specific_news(self, code, stock_name):
        """
        Fetches specific news for a stock (Simple implementation using Naver Finance Search).
        Returns a list of titles.
        """
        # For MVP, we'll try to use the research_scraper's logic or simple requests
        # This is a placeholder for the "2nd Priority Check"
        # In a real scenario, this would scrape 'item/news.naver'
        return []

    def analyze_candidates(self, candidates):
        """
        Main Logic:
        1. Calculate Sentinel Score for all candidates.
        2. Rank and pick Top 10.
        3. Apply Portfolio Logic (Filter Sells if not held).
        4. Generate Final Recommendations.
        """
        print("[Advisor] Analyzing Candidates...")
        
        results = []
        
        for stock in candidates:
            # 1. Sentinel Analysis
            analysis = self.sentinel.analyze_stock(stock)
            signal = analysis['signal']
            score = analysis['score']
            
            code = stock.get('code')
            name = stock.get('name')
            current_price = float(stock.get('close', 0))
            
            # 2. Portfolio Logic
            in_portfolio = code in self.portfolio
            
            action = "WATCH"
            target_price = 0
            
            # [User Rule] Sell Signal Logic
            if signal == "SELL":
                if in_portfolio:
                    action = "SELL_EXECUTE"
                    # Simple rule: Current Price
                    target_price = current_price 
                else:
                    # [User Rule] "If Sell Signal and Not Held -> Do not include in report"
                    continue 

            # Buy Signal Logic
            elif "BUY" in signal:
                if in_portfolio:
                    action = "BUY_MORE" # Accumulate
                else:
                    action = "BUY_NEW"
                
                # Simple Target: +5% (MVP)
                target_price = current_price * 1.05
            
            # Store Result
            results.append({
                'code': code,
                'name': name,
                'price': current_price,
                'signal': signal,
                'score': score,
                'action': action,
                'target_price': target_price,
                'in_portfolio': in_portfolio,
                'factors': analysis['factors']
            })
            
        # 3. Rank by Score
        results.sort(key=lambda x: x['score'], reverse=True)
        
        # 4. Top 10 Filtering
        top_picks = results[:10]
        
        # 5. News Integration (Mock for now, can expand)
        # for pick in top_picks:
        #     pick['news'] = self.fetch_specific_news(pick['code'], pick['name'])
            
        return top_picks

    def generate_report(self, candidates):
        """
        Generates the final human-readable report string.
        """
        analysis_results = self.analyze_candidates(candidates)
        
        # 1. Ask Gemini for the narrative part
        market_context = f"Analyzed {len(candidates)} stocks. Found {len(analysis_results)} actionable items."
        gemini_guide = self.gemini.generate_trading_guide(market_context, analysis_results)
        
        # 2. Add specific Action Items
        report = f"{gemini_guide}\n\n"
        report += "📋 **Action Items (Portfolio Integrated)**\n"
        
        for item in analysis_results:
            icon = "🔴" if "BUY" in item['action'] else "🔵"
            if item['action'] == "WATCH": icon = "👀"
            
            portfolio_tag = " [보유중]" if item['in_portfolio'] else ""
            
            report += f"{icon} **{item['name']}** ({item['action']}){portfolio_tag}\n"
            report += f"   - Signal: {item['signal']} (Score: {item['score']})\n"
            report += f"   - Price: {item['price']} -> Target: {int(item['target_price'])}\n"
            
        return report, analysis_results
