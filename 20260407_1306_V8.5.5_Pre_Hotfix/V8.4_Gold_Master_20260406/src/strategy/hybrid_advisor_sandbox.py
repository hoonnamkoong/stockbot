import os
import sys
import json
import urllib.parse
from datetime import datetime
import pandas as pd
import google.generativeai as genai
from bs4 import BeautifulSoup
import requests
from sklearn.ensemble import RandomForestClassifier
import joblib

# Add parent directory to path to allow imports from src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.strategy.advisor import StrategyAdvisor, GeminiAgent

# Load environment via the trade manager
try:
    from trade.auth import load_env
except ImportError:
    from src.trade.auth import load_env

class HybridAnalyzerSandbox:
    def __init__(self, data_path, model_path=None, version="v_unknown"):
        self.data_path = data_path
        self.model_path = model_path
        self.version = version
        self.ml_model = None
        self.gemini_agent = GeminiAgent()
        # Ensure API key is loaded for Gemini
        load_env()
        self.api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_KEY')
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel('gemini-2.5-flash-lite')
        else:
            self.model = None
            print("[HybridSandbox] Warning: No API Key found for Gemini.")
        
        # Auto-load model if path provided
        if self.model_path and os.path.exists(self.model_path):
            self.load_model(self.model_path)

    def train_ml_model(self):
        """Train a lightweight Random Forest model using historical scraping data."""
        # ... (implementation kept same as before) ...
        # (Included in full tool call for brevity, but logically same)
        print(f"[HybridSandbox] Loading historical data from {self.data_path}...")
        try:
            df = pd.read_csv(self.data_path)
            # ... rename and clean ...
            column_map = {'현재가': 'price', '등락률': 'change_rate', '현재_외국인비중': 'foreign_rate', '당일_게시글수': 'recent_posts_count', 'code': 'code', 'date': 'date'}
            df = df.rename(columns=column_map)
            df = df.dropna(subset=['price', 'change_rate'])
            
            def clean_numeric(val):
                if pd.isna(val): return 0.0
                val_str = str(val).replace(',', '').replace('%', '').strip()
                try: return float(val_str)
                except: return 0.0

            df['change_rate_num'] = df['change_rate'].apply(clean_numeric)
            df['foreign_rate_num'] = df['foreign_rate'].apply(clean_numeric)
            df['recent_posts'] = df['recent_posts_count'].apply(lambda x: int(clean_numeric(x)))
            df['date_dt'] = pd.to_datetime(df['date'], errors='coerce')
            
            def calculate_relative_hype(row):
                posts = row['recent_posts']
                hour = 15 
                if '취합시간' in row and pd.notna(row['취합시간']):
                    try:
                        time_str = str(row['취합시간'])
                        if ':' in time_str: hour = int(time_str.split(':')[0])
                    except: pass
                if 9 <= hour < 12: threshold = 40
                elif 12 <= hour < 14: threshold = 60
                elif 14 <= hour < 24: threshold = 100
                else: threshold = 10
                return min(posts / threshold, 10.0)
                
            df['relative_hype'] = df.apply(calculate_relative_hype, axis=1)
            df = df.sort_values(by=['code', 'date_dt'])
            df['next_day_change'] = df.groupby('code')['change_rate_num'].shift(-1)
            train_df = df.dropna(subset=['next_day_change']).copy()
            
            if len(train_df) == 0:
                print("[HybridSandbox] Not enough T+1 data for training.")
                return False
                
            train_df['target'] = (train_df['next_day_change'] > 0).astype(int)
            X = train_df[['change_rate_num', 'foreign_rate_num', 'relative_hype']]
            y = train_df['target']
            
            print(f"[HybridSandbox] Training ML model on {len(X)} records...")
            self.ml_model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
            self.ml_model.fit(X, y)
            print("[HybridSandbox] Model training complete.")
            print("[HybridSandbox] Model training complete.")
            return True
        except Exception as e:
            print(f"[HybridSandbox] Model training failed: {e}")
            return False

    def save_model(self, path):
        if self.ml_model:
            joblib.dump(self.ml_model, path)
            print(f"[HybridSandbox] Model saved to {path}")
            return True
        return False

    def load_model(self, path):
        if os.path.exists(path):
            self.ml_model = joblib.load(path)
            print(f"[HybridSandbox] Model loaded from {path}")
            return True
        return False

    def fetch_live_news(self, stock_name):
        """Fetch news titles from Naver Search for NLP scoring"""
        news_titles = []
        try:
            encoded_query = urllib.parse.quote(stock_name)
            url = f"https://m.search.naver.com/search.naver?where=m_news&query={encoded_query}&sm=mtb_jum&sort=1"
            headers = {"User-Agent": "Mozilla/5.0 (Linux; Android 10; K)"}
            res = requests.get(url, headers=headers, timeout=3)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            groups = soup.select('.group_news')
            for g in groups[:5]: # Get up to 5 news titles
                links = g.find_all('a')
                valid_links = [a for a in links if len(a.get_text(strip=True)) > 10]
                if valid_links:
                    news_titles.append(valid_links[0].get_text(strip=True))
        except Exception as e:
            return [f"News fetch failed: {e}"]
        
        return news_titles if news_titles else ["No recent news."]

    def ask_ai_sentiment(self, stock_name, news_titles):
        """Ask Gemini to grade the real-time news from -50 (Bad) to +50 (Good)"""
        if not self.model or news_titles == ["No recent news."]:
            return 0, "No news or AI disabled."
            
        news_context = "\n".join([f"- {n}" for n in news_titles])
        prompt = f"""
        Role: Stock News Analyst.
        Task: Analyze the recent news titles for the Korean stock '{stock_name}' and provide a Sentiment Score.
        Score Guidelines:
        -50 to -30: Critical bad news (e.g., 유상증자, 배임, 상장폐지, 거래정지, 대규모 적자)
        -29 to -1: Mild bad news or selling pressure
        0: Neutral or irrelevant news
        1 to 29: Mild good news
        30 to 50: Critical good news (e.g., 대규모 수주, 흑자전환, 무상증자, 허가 승인, 독점)
        
        Recent News:
        {news_context}
        
        Output Requirements:
        1. Exact Score (integer from -50 to 50)
        2. One sentence reasoning.
        Format EXACTLY like: Score: [SCORE] | Reason: [REASON]
        """
        
        try:
            response = self.model.generate_content(prompt)
            result = response.text.strip()
            # Parse 'Score: 40 | Reason: ...'
            if "Score:" in result:
                parts = result.split('|')
                score_part = parts[0].replace('Score:', '').strip()
                reason = parts[1].replace('Reason:', '').strip() if len(parts) > 1 else "Parsed reason"
                return int(score_part), reason
            return 0, result
        except Exception as e:
            return 0, f"AI Parsing failed: {e}"

    def simulate_pipeline(self, current_candidates):
        """Run the hybrid pipeline on current candidates"""
        if not self.ml_model:
            print("[HybridSandbox] ML Model not trained. Run train_ml_model() first.")
            return

        print("\n=== 🎯 HYBRID SANDBOX PIPELINE ===")
        print("1. Running ML Model for Base Probabilities...")
        results = []
        
        for idx, stock in enumerate(current_candidates):
            try:
                # Prepare features
                price = float(str(stock.get('현재가', stock.get('price', 0))).replace(',', ''))
                change = float(str(stock.get('등락률', stock.get('change_rate', '0'))).replace('%', '').replace(',', ''))
                f_rate = float(str(stock.get('현재_외국인비중', stock.get('foreign_rate', '0'))).replace('%', ''))
                posts = int(str(stock.get('당일_게시글수', stock.get('recent_posts_count', 0))).replace(',', ''))
                
                # Calculate Relative Hype for Live Pipeline
                current_hour = (datetime.utcnow().hour + 9) % 24
                if 9 <= current_hour < 12: threshold = 40
                elif 12 <= current_hour < 14: threshold = 60
                elif 14 <= current_hour < 24: threshold = 100
                else: threshold = 10
                
                relative_hype = min(posts / threshold, 10.0)
                
                # Predict ML Probability (0 to 1 -> 0 to 100 scale)
                # Ensure column names match what was trained
                features = pd.DataFrame([[change, f_rate, relative_hype]], columns=['change_rate_num', 'foreign_rate_num', 'relative_hype'])
                prob_up = self.ml_model.predict_proba(features)[0][1] * 100
                
                # Base scoring mimicking old logic for comparison but strictly ML driven
                results.append({
                    'code': stock.get('code'),
                    'name': stock.get('종목명', stock.get('name')),
                    'ml_prob': prob_up,
                    'change': change,
                    'f_rate': f_rate,
                    'posts': posts,
                    'relative_hype': relative_hype
                })
            except Exception as e:
                continue
                
        # Sort by ML Probability
        results.sort(key=lambda x: x['ml_prob'], reverse=True)
        top_picks = results[:5] # Only run AI on top 5 for speed
        
        print(f"\n2. Running AI NLP Sentiment on Top {len(top_picks)} ML Picks...")
        
        for pick in top_picks:
            print(f"  -> Fetching news for: {pick['name']}")
            news = self.fetch_live_news(pick['name'])
            nlp_score, reason = self.ask_ai_sentiment(pick['name'], news)
            
            pick['nlp_score'] = nlp_score
            pick['hybrid_score'] = pick['ml_prob'] + nlp_score
            pick['reason'] = reason
            
        # Re-sort Top Picks by Hybrid Score
        top_picks.sort(key=lambda x: x['hybrid_score'], reverse=True)
        
        print("\n=== 📊 HYBRID PIPELINE RESULTS ===")
        for i, pick in enumerate(top_picks, 1):
            print(f"#{i} {pick['name']} (Code: {pick['code']})")
            print(f"  - ML Prob:  {pick['ml_prob']:.1f}%")
            print(f"  - AI Score: {pick['nlp_score']} / 50")
            print(f"  - HYBRID:   {pick['hybrid_score']:.1f} Total Score")
            print(f"  - AI Reason:{pick['reason']}")
            print(f"  - Meta:     Change {pick['change']:+.1f}%, Foreign {pick['f_rate']}%, Hype {pick['relative_hype']:.1f}x (Posts {pick['posts']})")
            print("-" * 50)
        
        return top_picks

    def predict_all(self, current_candidates):
        """Returns ML probabilities for all candidates without running NLP sentiment (for fast portfolio evaluation)"""
        if not self.ml_model:
            return []

        results = []
        for stock in current_candidates:
            try:
                price = float(str(stock.get('현재가', stock.get('price', 0))).replace(',', ''))
                change = float(str(stock.get('등락률', stock.get('change_rate', '0'))).replace('%', '').replace(',', ''))
                f_rate = float(str(stock.get('현재_외국인비중', stock.get('foreign_rate', '0'))).replace('%', ''))
                posts = int(str(stock.get('당일_게시글수', stock.get('recent_posts_count', 0))).replace(',', ''))
                
                current_hour = (datetime.utcnow().hour + 9) % 24
                if 9 <= current_hour < 12: threshold = 40
                elif 12 <= current_hour < 14: threshold = 60
                elif 14 <= current_hour < 24: threshold = 100
                else: threshold = 10
                
                relative_hype = min(posts / threshold, 10.0)
                
                features = pd.DataFrame([[change, f_rate, relative_hype]], columns=['change_rate_num', 'foreign_rate_num', 'relative_hype'])
                prob_up = self.ml_model.predict_proba(features)[0][1] * 100
                
                results.append({
                    'code': stock.get('code'),
                    'name': stock.get('종목명', stock.get('name')),
                    'price': price,
                    'ml_prob': prob_up,
                    'change': change,
                })
            except Exception as e:
                continue
                
        results.sort(key=lambda x: x['ml_prob'], reverse=True)
        return results

if __name__ == "__main__":
    # 1. Load the latest scraped data to mock 'current execution'
    latest_file = r"C:\Users\Hoon_DT\gemini\stock\data\latest_stocks.json"
    archive_file = r"C:\Users\Hoon_DT\gemini\stock\scraping data\combined_scraping_data.csv"
    
    if os.path.exists(latest_file):
        with open(latest_file, 'r', encoding='utf-8') as f:
            candidates = json.load(f)
            
        sandbox = HybridAnalyzerSandbox(data_path=archive_file)
        
        # Train Model
        success = sandbox.train_ml_model()
        if success:
            # Simulate Pipeline
            sandbox.simulate_pipeline(candidates)
    else:
        print(f"Could not find {latest_file} to run sandbox.")
