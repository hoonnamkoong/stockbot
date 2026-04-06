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

# [V8.4.6 Gold Master] AI 분석 엔진 및 전략 코디네이터
# 개편 사항: 동적 모델 로더, 환경변수 통합, 데이터 인젝션 안정화

# --- Trade Module Imports ---
from src.trade.auth import get_access_token, load_env
from src.trade.balance import get_balance

class GeminiAgent:
    """
    [V8.4.6] 최신 모델 동적 탐색 엔진 적용
    """
    def __init__(self):
        # 환경변수 통합 로드 (Double Defense)
        self.api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_KEY')
        self.model = None
        self.model_name = "Unknown"
        
        if not self.api_key:
            print("[GeminiAgent] 🚨 에러: API 키(GOOGLE_API_KEY)가 감지되지 않습니다.")
            return

        genai.configure(api_key=self.api_key)
        
        try:
            # 사용 가능한 모델 리스트 동적 확보
            available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            
            # 우선순위에 따른 모델 매칭 (2.0 -> 1.5 -> 1.0)
            priority_list = ['models/gemini-2.0-flash', 'models/gemini-1.5-flash', 'models/gemini-1.5-pro']
            selected = next((m for m in priority_list if m in available_models), available_models[0] if available_models else 'gemini-1.5-flash')
            
            self.model = genai.GenerativeModel(selected)
            self.model_name = selected
            print(f"[GeminiAgent] ✅ 최신 동적 모델 로드 성공: {selected}")
        except Exception as e:
            print(f"[GeminiAgent] 🚨 모델 탐색 실패, 기본값 사용: {e}")
            self.model = genai.GenerativeModel('gemini-1.5-flash')
            self.model_name = 'gemini-1.5-flash'

    def generate_trading_guide(self, market_context, signals):
        """[V8.4.6] 31개 종목 누락 방지 및 딥다이브 리포트 생성"""
        if not self.model: return "⚠️ Gemini API 초기화 실패: 리포트를 생성할 수 없습니다."
        if not signals: return "⚠️ 분석할 시그널 종목 데이터가 전달되지 않았습니다."

        # [데이터 정제] 토론방 본문이 너무 길어 API 용량을 초과하지 않도록 300자 제한
        cleaned_signals = []
        for s in signals:
            item = s.copy()
            if 'latest_posts' in item:
                for p in item['latest_posts']:
                    if 'body' in p: p['body'] = str(p['body'])[:300]
            cleaned_signals.append(item)

        prompt = f"""
        당신은 대한민국 주식 시장 전문 퀀트 애널리스트입니다.
        아래 시장 상황과 {len(cleaned_signals)}개 종목의 토론방 Buzz 데이터를 바탕으로 '오늘 밤의 필독 리포트'를 작성하세요.
        
        [시장상황] {market_context}
        [데이터] {json.dumps(cleaned_signals, ensure_ascii=False)}
        
        **출력 가이드:**
        1. 가장 유망한 'Top 3 대장주'를 선정하고 그 이유를 토론방 여론과 연계해 설명할 것.
        2. 주의해야 할 '리스크 종목'을 1개 선정할 것.
        3. 강조는 오직 마크다운(**)만 사용하고, 전문적이고 신뢰감 있는 어조를 유지할 것.
        4. HTML 태그(<br>, <b> 등)를 절대 사용하지 말 것.
        """
        try:
            response = self.model.generate_content(prompt)
            if response and response.text:
                res_text = response.text
                # HTML 태그 강제 제거 (보안 레이어)
                res_text = re.sub(r'<[^>]*>', '', res_text)
                return res_text.strip()
            return "⚠️ AI 분석 결과가 비어있습니다."
        except Exception as e:
            return f"⚠️ 리포트 생성 중 오류 발생: {e}"

    def evaluate_momentum(self, stock, news, dart):
        """[V8.4.7] 개별 종목의 모멘텀을 AI가 최종 검증 (Engine 호출용)"""
        if not self.model: return "WATCH"
        
        prompt = f"""
        종목명: {stock.get('name')} ({stock.get('code')})
        현재 Buzz: {stock.get('post_count')} posts
        최근 뉴스: {news}
        공시 분석: {dart}
        
        위 데이터를 바탕으로 이 종목의 단기 모멘텀을 평가하세요.
        반드시 'BUY', 'WATCH', 'REJECT' 중 하나의 단어로 시작하고, 그 뒤에 한 줄 이유를 덧붙이세요.
        """
        try:
            response = self.model.generate_content(prompt)
            return response.text.strip() if response.text else "WATCH"
        except:
            return "WATCH"

    def analyze_bulk_sentiment(self, bulk_data):
        """기존 벌크 감성 분석 로직 유지 (모델 동적 적용)"""
        if not self.model: return {}
        try:
            processed_bulk = []
            for s in bulk_data:
                processed_bulk.append({
                    "code": s.get('code'),
                    "name": s.get('name'),
                    "bodies": [str(b)[:300] for b in s.get('bodies', [])]
                })

            prompt = f"다음 주식 종목들의 토론방 분위기를 분석하여 감성 점수(-10 ~ 10)를 JSON 형식으로만 답변하세요:\n{json.dumps(processed_bulk, ensure_ascii=False)}"
            
            response = self.model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            return json.loads(response.text)
        except:
            return {s.get('code'): 0 for s in bulk_data}

class StrategyAdvisor:
    def __init__(self):
        from .virtual_portfolio import VirtualPortfolioManager
        from .engine import StrategyEngine
        self.vpm = VirtualPortfolioManager()
        self.engine = StrategyEngine()
        self.gemini = GeminiAgent()

    def generate_report(self, candidates, allow_buy=True):
        """[V8.4.7] 개장일 중심 리포트 생성 로직"""
        # 기술적 분석 및 시뮬레이션 실행 (종목 대응은 그대로 수행)
        all_results = self.engine.execute_simulation(candidates, allow_buy=allow_buy)
        
        # [V8.4.7 Fix] AI 분석에는 Buzz 필터를 통과한 정예 종목(candidates)을 직접 전달
        # 이를 통해 allow_buy=False인 밤 시간대에도 데이터 단절 없이 리포트가 생성됨
        market_context = f"{len(candidates)}개 종목 Buzz 필터 통과. 시장 주도 섹터 및 모멘텀 분석."
        gemini_guide = self.gemini.generate_trading_guide(market_context, candidates)
        
        summary = f"\n---\n📊 **V8.4.7 Gold Master 시스템 리포트**\n"
        summary += f"📅 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        
        buy_targets = [r for r in all_results if r.get('signal') == 'BUY']
        if buy_targets:
            summary += f"🔥 매수 대상: {', '.join([t['name'] for t in buy_targets])}\n"
        
        return f"{gemini_guide}\n{summary}", all_results
