
import os
import sys
import json
import time
import requests
import urllib.parse
import datetime
import google.generativeai as genai
from collections import Counter
import re
from bs4 import BeautifulSoup

# Add parent directory to path to allow imports from src/trade
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

try:
    from trade.auth import get_access_token, load_env
except ImportError:
    from src.trade.auth import get_access_token, load_env

from .engine import StrategyEngine

# --- 1. SentinelV Logic (Extracted from scraper.py) ---
# SentinelV is now replaced by StrategyEngine in engine.py

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
        Task: Write a "Trading Guide" (매매 가이드) in a **Narrative/Descriptive Style** (서술형).
        Current Date: {msg_date}
        
        Data Sources:
        1. Market Context: {market_context}
        2. Top Picks ( Signals & News): {json.dumps(sentinel_signals, ensure_ascii=False, indent=2)}
        
        Requirement:
        - Do NOT use simple bullet points for the main analysis. Write cohesive paragraphs (2-3 sentences per stock or group) that explain the "Why".
        - **PRIORITY**: If there are 'SELL' signals for stocks marked as '[보유중]' (In Portfolio), analyze if they are urgent risk management or profit-taking.
        - **RIDE THE WINNER**: If a stock is at high profit but the 'Signal' says HOLD/BUY (strong momentum), encourage holding it longer while watching for a trend reversal. Do not suggest selling just because it's up 10%.
        - **Structure**:
            1. **Market/Sector Overview**: Brief context if applicable.
            2. **Portfolio Management & Top Candidate Analysis**: For the top recommended stocks AND held stocks with sell/hold signals, explicitly state your **Prediction** (예측), **Argument/Reasoning** (주장/근거), and **Why** based on the News, Signal, and Profit Rate.
            3. **Risks/Disclosures**: Mention any critical risks found in the news.
        - **Tone**: Persuasive technical analysis, professional, objective.
        - **Language**: Korean (Natural, Expert tone).
        """
        
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"Gemini Error: {e}"

# --- 3. Strategy Advisor (The Coordinator) ---
class StrategyAdvisor:
    def __init__(self):
        self.engine = StrategyEngine()
        self.gemini = GeminiAgent()
        self._cached_portfolio = None
        
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
            # Determine TR ID based on URL (Real vs Virtual)
            # Real: TTTC8434R, Virtual: VTTC8434R
            "tr_id": "VTTC8434R" if "vts" in base_url.lower() else "TTTC8434R",
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
        Fetches specific news for a stock.
        Priority 1: Naver Search (Mobile) - Broader coverage
        Priority 2: Naver Finance (Item News) - Specific to stock
        """
        news_list = []
        
        # --- Priority 1: Naver Mobile Search ---
        try:
            encoded_query = urllib.parse.quote(stock_name)
            url = f"https://m.search.naver.com/search.naver?where=m_news&query={encoded_query}&sm=mtb_jum&sort=1"
            headers = {
                "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36"
            }
            
            res = requests.get(url, headers=headers, timeout=3)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            groups = soup.select('.group_news')
            for g in groups[:3]: # Top 3 items
                # Naver Mobile structure uses dynamic classes. 
                # Strategy: Find the anchor tag with the longest text (likely the title)
                links = g.find_all('a')
                if not links: continue
                
                # Filter out small icon links or buttons
                valid_links = [a for a in links if len(a.get_text(strip=True)) > 10]
                
                if valid_links:
                    # Usually the first long link is the title in the card
                    title_tag = valid_links[0]
                    title = title_tag.get_text(strip=True)
                    link = title_tag['href']
                    
                    # Try to find source (usually a short link/span before the title, or inside .press class)
                    source = "NaverSearch"
                    try:
                        press = g.select_one('.press')
                        if press: source = press.get_text(strip=True)
                    except: pass
                    
                    news_list.append({'title': f"[{source}] {title}", 'link': link})
                    
        except Exception as e:
            print(f"[Advisor] Naver Search Fetch Failed for {stock_name}: {e}")

        # --- Priority 2: Fallback to Naver Finance if Search failed ---
        if not news_list:
            try:
                # url = f"https://finance.naver.com/item/news_news.naver?code={code}&page=1"
                # headers = {
                #     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                #     "Referer": f"https://finance.naver.com/item/main.naver?code={code}"
                # }
                
                # res = requests.get(url, headers=headers, timeout=3)
                # res.encoding = 'EUC-KR'
                # soup = BeautifulSoup(res.text, 'html.parser')
                
                # titles = soup.select('.title')
                # if not titles: titles = soup.select('.tit')
                # if not titles: 
                #     links = soup.find_all('a', class_='tit')
                #     if links: titles = links
                
                # for t in titles[:3]:
                #     a_tag = len(t.find_all('a')) > 0 and t.find('a') or (t.name == 'a' and t)
                    
                #     if a_tag:
                #         title = a_tag.get_text(strip=True)
                #         link = "https://finance.naver.com" + a_tag['href']
                #         news_list.append({'title': title, 'link': link})
                # --- Simplified Fallback (Commented out to rely on search for now as per user request to SWITCH) ---
                pass
            except Exception as e:
                print(f"[Advisor] Naver Finance Fallback Failed: {e}")
            
        return news_list

    def get_portfolio(self):
        """Returns cached portfolio or fetches new if needed."""
        if self._cached_portfolio is None:
            self._cached_portfolio = self.fetch_portfolio()
        return self._cached_portfolio

    def analyze_candidates(self, candidates):
        """
        Main Logic:
        1. Calculate Score for all candidates.
        2. Merge Portfolio stocks into candidates.
        3. Rank and pick Top 10.
        4. Generate Final Recommendations.
        """
        print("[Advisor] Analyzing Candidates...")
        portfolio = self.get_portfolio()
        
        # 1. Ensure Portfolio stocks are in the candidate list
        existing_codes = {c.get('code') for c in candidates}
        for code, info in portfolio.items():
            if code not in existing_codes:
                candidates.append({
                    'code': code,
                    'name': info['name'],
                    'price': info['current_price'],
                    'change_rate': f"{info['profit_rate']}%", # Approximation
                    'source': 'portfolio'
                })

        results = []
        for stock in candidates:
            code = stock.get('code')
            name = stock.get('name')
            
            # --- 1. Scoring (Delegated to Engine) ---
            score, p_change = self.engine.calculate_score(stock)
            
            # --- 2. Signal (Delegated to Engine) ---
            in_portfolio = code in portfolio
            p_info = portfolio.get(code)
            profit_rate = p_info.get('profit_rate', 0) if in_portfolio else 0.0
            
            signal, confidence = self.engine.get_signal(score, p_change, in_portfolio, profit_rate)
            
            action = "WATCH"
            target_price = 0
            
            # --- 3. Action Assignment ---
            if signal == "SELL":
                if in_portfolio:
                    action = "SELL_EXECUTE"
                    target_price = stock.get('price', 0)
                else:
                    continue # Skip non-held sell signals
            elif "BUY" in signal:
                action = "BUY_MORE" if in_portfolio else "BUY_NEW"
                target_price = float(stock.get('price', 0)) * 1.05
                
            results.append({
                'code': code,
                'name': name,
                'price': stock.get('price', 0),
                'signal': signal,
                'score': score,
                'action': action,
                'target_price': target_price,
                'in_portfolio': in_portfolio,
                'profit_rate': profit_rate,
                'today_change': p_change,
                'factors': {}, # Detailed factors can be added to engine later
                'custom_reason': ""
            })
            
        # 3. Rank by Score
        results.sort(key=lambda x: x['score'], reverse=True)
        
        # 4. Top 10 Filtering
        top_picks = results[:10]
        
        # 5. News Integration (Real-time)
        print(f"[Advisor] Fetching news for Top {len(top_picks)} candidates...")
        for pick in top_picks:
             time.sleep(0.1) 
             pick['news'] = self.fetch_specific_news(pick['code'], pick['name'])
            
        return top_picks

    def generate_report(self, candidates):
        """
        Generates the final human-readable report string.
        """
        # 1. Analyze ALL candidates first
        all_results = self.analyze_candidates(candidates)
        
        # 2. Filter for Report (Top 6 + Sells)
        # - Top 6 by Score
        top_6 = all_results[:6]
        
        # - Forced Include: Any SELL action in portfolio, even if not in Top 6
        forced_sells = [
            item for item in all_results[6:] 
            if item['action'] == "SELL_EXECUTE"
        ]
        
        final_report_items = top_6 + forced_sells
        
        # 3. Ask Gemini for the narrative part (Filtered Context)
        market_context = f"Analyzed {len(candidates)} stocks. Reporting Top {len(final_report_items)} items."
        gemini_guide = self.gemini.generate_trading_guide(market_context, final_report_items)
        
        # 4. Add specific Action Items
        report = f"{gemini_guide}\n\n"
        report += "📋 **Action Items (Top 6 + Critical Sells)**\n"
        
        for item in final_report_items:
            icon = "🔴" if "BUY" in item['action'] else "🔵"
            if item['action'] == "WATCH": icon = "👀"
            if item['action'] == "SELL_EXECUTE": icon = "🚨" # Distinct icon for sell
            
            portfolio_tag = " [보유중]" if item['in_portfolio'] else ""
            
            report += f"{icon} **{item['name']}** ({item['action']}){portfolio_tag}\n"
            report += f"   - Signal: {item['signal']} (Score: {item['score']})\n"
            report += f"   - Price: {item['price']} -> Target: {int(item['target_price'])}\n"
            
        return report, final_report_items
