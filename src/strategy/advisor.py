
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

# --- 2. Gemini Agent Logic (Upgraded to 3.0 Pro) ---
class GeminiAgent:
    def __init__(self):
        load_env()
        self.api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_KEY')
        self.model = None
        
        if self.api_key:
            genai.configure(api_key=self.api_key)
            # [2026-04-06 Update] Use Gemini 3.1 series as requested
            models_to_try = ['gemini-3.1-flash', 'gemini-3.1-pro', 'gemini-1.5-flash']
            
            for m in models_to_try:
                try:
                    # Initialize model
                    model_obj = genai.GenerativeModel(m)
                    
                    # Test generation (minimal) to avoid AttributeError on model_name or connectivity issues
                    # If it doesn't throw, we consider it loaded.
                    self.model = model_obj
                    self.model_name = m
                    print(f"[GeminiAgent] Successfully loaded model: {m}")
                    break
                except Exception as e:
                    print(f"[GeminiAgent] Fallback from {m} due to error: {e}")
            
            if not self.model:
                print("[GeminiAgent] Warning: No models were loaded successfully.")
        else:
            print("[GeminiAgent] Warning: No API Key found.")

    def evaluate_momentum(self, stock_info, news_list, dart_info):
        """
        신규 종목 매수 여부를 결정하는 최종 인공지능 평가 엔진 (JSON 반환 강제)
        """
        if not self.model:
            return {"decision": "REJECTED", "momentum_score": 0, "telegram_narrative": "API Key Error"}
            
        prompt = f"""
        Role: Aggressive Momentum Stock Trader
        Task: Evaluate if the public frenzy and smart money (foreigners) are justified by an explosive catalyst (News/DART).
        
        Data:
        - Target Stock: {json.dumps(stock_info, ensure_ascii=False)}
        - News Headlines: {json.dumps(news_list, ensure_ascii=False)}
        - DART Premium: {json.dumps(dart_info, ensure_ascii=False)}
        
        Rule:
        - Analyze if this is a fresh, real catalyst or just a simple thematic noise (Gap & Crap).
        - Provide a momentum score (1-10). If >= 7, set decision to "APPROVED", else "REJECTED".
        - 'telegram_narrative' should explicitly write a narrative of WHY the market is crazy about this, predicting tomorrow's opening gap.
        
        Output Strictly in valid JSON format:
        {{
            "decision": "APPROVED" | "REJECTED",
            "momentum_score": 8,
            "catalyst_summary": "Short summary of the core catalyst",
            "telegram_narrative": "Detailed narrative for telegram report..."
        }}
        """
        try:
            # Forcing JSON generation through config if supported, otherwise rely on prompt
            response = self.model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            return json.loads(response.text)
        except Exception as e:
            print(f"[GeminiAgent] Momentum Evaluation Error: {e}")
            return {"decision": "REJECTED", "momentum_score": 0, "telegram_narrative": f"Error: {e}"}

    def generate_trading_guide(self, market_context, sentinel_signals):
        """기존 보유 종목 보고용 레거시 유지 (원할 경우 고도화 가능)"""
        if not self.model: return "Gemini API Key missing."
        prompt = f"Write a narrative trading summary based on: {json.dumps(sentinel_signals, ensure_ascii=False)}. Explain why we sold or held."
        try:
            return self.model.generate_content(prompt).text
        except:
            return "Error generating generic guide."

# --- 3. Strategy Advisor (The Coordinator) ---
class StrategyAdvisor:
    def __init__(self):
        from .virtual_portfolio import VirtualPortfolioManager
        self.vpm = VirtualPortfolioManager()
        self.engine = StrategyEngine()
        self.gemini = GeminiAgent()
        self._cached_portfolio = None
        
    def fetch_portfolio(self):
        """
        Fetches holdings from KIS API (Real/Virtual) or Local JSON.
        """
        is_virtual = os.environ.get("KIS_IS_VIRTUAL", "false").lower() == "true"
        holdings = {}

        if not is_virtual:
            print("[Advisor] Fetching REAL KIS Portfolio...")
            try:
                # [SAFETY] Import and call inside try block to prevent crash if module fails
                from trade.balance import get_balance
                res = get_balance()
                
                if res and isinstance(res, dict) and "error" not in res:
                    for h in res.get('holdings', []):
                        holdings[h['code']] = {
                            'name': h['name'],
                            'qty': h['qty'],
                            'avg_price': h['avg_price'],
                            'current_price': h['current_price'],
                            'profit_rate': h['profit_rate']
                        }
                    print(f"[Advisor] REAL Portfolio loaded: {len(holdings)} items")
                    return holdings
                else:
                    err = res.get('error') if res else 'Unknown error'
                    print(f"[Advisor] ⚠️ REAL Balance Fetch Skip: {err}")
            except Exception as e:
                # [CRITICAL] Catch all exceptions to guarantee report generation continues
                print(f"[Advisor] ❌ CRITICAL: REAL Portfolio Fetch Exception (Skipping): {e}")

        # Fallback to Virtual Portfolio
        print("[Advisor] Fetching Virtual Portfolio (Fallback/Mock)...")
        try:
            port_data = self.vpm.get_portfolio()
            for code, info in port_data.items():
                qty = info.get('quantity', 0)
                if qty > 0:
                    avg_price = info.get('average_buy_price', 0.0)
                    
                    # Fetch current price from Naver dynamically to compute profit
                    current_price = avg_price
                    try:
                        res = requests.get(f"https://finance.naver.com/item/main.naver?code={code}", timeout=3)
                        soup = BeautifulSoup(res.text, 'html.parser')
                        price_tag = soup.select_one(".no_today .blind")
                        if price_tag:
                            current_price = float(price_tag.text.replace(',', ''))
                    except Exception as naver_e:
                        print(f"[Advisor] Failed to fetch current price for {code}: {naver_e}")

                    profit_rate = ((current_price - avg_price) / avg_price) * 100.0 if avg_price > 0 else 0.0
                    
                    holdings[code] = {
                        'name': info.get('name', 'Unknown'),
                        'qty': qty,
                        'avg_price': avg_price,
                        'current_price': current_price,
                        'profit_rate': profit_rate
                    }
        except Exception as e:
            print(f"[Advisor] Virtual Portfolio Fetch Error: {e}")
            
        print(f"[Advisor] Portfolio loaded: {len(holdings)} items")
        return holdings

    def check_dart_filings(self, stock_name, stock_code):
        load_env()
        dart_key = os.environ.get('DART_API_KEY')
        result = {"premium": [], "hard_reject": False, "summary": "No Issues"}
        
        # Hard Reject & Premium Keywords
        reject_kws = ["전환사채", "신주인수권부사채", "유상증자", "주식등의대량보유상황보고서", "임원ㆍ주요주주특정증권등소유상황보고서"]
        premium_kws = ["단일판매ㆍ공급계약체결", "자기주식취득", "무상증자"]

        if not dart_key:
            result["summary"] = "DART API Key Missing (Skipped)"
            return result

        try:
            url = f"https://opendart.fss.or.kr/api/list.json?crtfc_key={dart_key}&bgn_de={datetime.datetime.now().strftime('%Y%m%d')}"
            res = requests.get(url, timeout=3)
            
            naver_url = f"https://finance.naver.com/item/news_notice.naver?code={stock_code}"
            n_res = requests.get(naver_url, timeout=3)
            soup = BeautifulSoup(n_res.text, 'html.parser')
            titles = soup.select('.title a')
            
            for t in titles:
                text = t.get_text(strip=True)
                if any(k in text for k in reject_kws):
                    result["hard_reject"] = True
                    result["summary"] = f"Hard Reject: {text}"
                    break
                if any(k in text for k in premium_kws):
                    result["premium"].append(text)
                    result["summary"] = f"Premium Filing Found: {text}"
                    
        except Exception as e:
            print(f"[Advisor] DART API Error for {stock_name}: {e}")
            result["summary"] = f"DART Error Exception (Safe Skip): {e}"
            
        return result

    def crosscheck_news_keywords(self, news_list, stock_name):
        return len(news_list) > 0

    def analyze_candidates(self, candidates, allow_buy=True):
        """
        Hybrid Engine Logic:
        1. Evaluate 1st Gate (4 Factors via Engine) for NEW candidates.
        """
        print("[Advisor] Running Hybrid Engine Candidate Analysis...")
        portfolio = self.get_portfolio()
        
        existing_codes = {c.get('code') for c in candidates}
        for code, info in portfolio.items():
            if code not in existing_codes:
                candidates.append({
                    'code': code,
                    'name': info['name'],
                    'price': info['current_price'],
                    'change_rate': 0.0,
                    'source': 'portfolio'
                })

        results = []
        for stock in candidates:
            code = stock.get('code')
            name = stock.get('name')
            in_portfolio = code in portfolio
            
            score, p_change = self.engine.calculate_score(stock)
            
            p_info = portfolio.get(code)
            profit_rate = p_info.get('profit_rate', 0) if in_portfolio else 0.0
            
            post_count_diff_pct = 0.0
            positive_rate = float(stock.get('positive_rate', 50.0))
            
            signal, confidence = self.engine.get_signal(
                score=score, 
                p_change=p_change, 
                in_portfolio=in_portfolio, 
                profit_rate=profit_rate,
                post_count_diff_pct=post_count_diff_pct,
                positive_rate=positive_rate
            )
            
            action = "WATCH"
            target_price = 0
            custom_reason = ""
            
            if in_portfolio:
                if "SELL" in signal:
                    action = "SELL_EXECUTE"
                    custom_reason = f"Adaptive Exit: {signal} (Profit: {profit_rate:.2f}%)"
                    
                    if signal == "SELL_ALL":
                        self.vpm.sell_stock(code)
                    elif signal == "SELL_HALF":
                        qty = p_info.get('qty', 0)
                        half_qty = max(1, int(qty / 2))
                        self.vpm.sell_stock(code, sell_qty=half_qty)
                        custom_reason += f" [50% Scale-out]"
                        
                elif signal == "HOLD":
                    action = "HOLD"
                    custom_reason = f"Velocity Hold (Profit: {profit_rate:.2f}%)"
            # --- New Candidates Evaluation (15:15 Only ideally) ---
            elif signal == "BUY_CANDIDATE":
                if not allow_buy:
                    continue # 장중 모드이므로 매수 후보 발굴 자체를 스킵
                
                # 2nd Gate: News & DART
                news_list = self.fetch_specific_news(code, name)
                if not self.crosscheck_news_keywords(news_list, name):
                    action = "REJECTED (No News)"
                    continue
                    
                dart_info = self.check_dart_filings(name, code)
                if dart_info.get("hard_reject"):
                    action = f"REJECTED (DART: {dart_info['summary']})"
                    continue
                    
                gemini_eval = self.gemini.evaluate_momentum(stock, news_list, dart_info)
                if gemini_eval.get("decision") == "APPROVED":
                    # [2026-04-06 Update] REAL Account: No auto-buy (Manual Recommend Only)
                    # GEMINI Portfolio (VPM): AUTO-Buy enabled for simulation & tracking
                    action = "BUY_RECOMMENDED" 
                    target_price = float(stock.get('price', 0))
                    custom_reason = gemini_eval.get("telegram_narrative", "AI Momentum Strong - Entry Recommended")
                    
                    self.vpm.buy_stock(code, name, target_price, quantity=20) # Virtual Auto-Trade
                else:
                    action = f"REJECTED (AI Score: {gemini_eval.get('momentum_score')})"

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
                'factors': stock,
                'custom_reason': custom_reason
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

    def generate_report(self, candidates, allow_buy=True):
        """
        Generates the final human-readable report string.
        """
        # 1. Analyze ALL candidates first
        all_results = self.analyze_candidates(candidates, allow_buy=allow_buy)
        
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
