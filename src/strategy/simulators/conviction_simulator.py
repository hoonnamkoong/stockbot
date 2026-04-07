import json
import os
import datetime
from .base_simulator import BaseSimulator
from ..advisor import GeminiAgent

class ConvictionSimulator(BaseSimulator):
    """
    [Sim 2] AI 컨빅션(Conviction) 전략
    - Gemini를 사용하여 1-5점의 확신도 점수를 부여합니다.
    - 점수에 따라 자산을 차등 배분하며, 15분 주기 재평가 및 청산 로직을 포함합니다.
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("Conviction", initial_cash)
        self.gemini = GeminiAgent()

    def assess_conviction(self, stock_data):
        """
        [AI 평가] 4대 항목 기반 Gemini 확신도 점수 산출
        항목: 1) Buzz 가속도, 2) 여론의 질, 3) 외인 수급, 4) 추세 위치
        """
        if not self.gemini or not self.gemini.model:
            return 2 # 기본 2점 (매수 제외)
            
        prompt = f"""
        주식 종목 [{stock_data.get('name')}]에 대한 다음 데이터를 분석하여 확신도 점수(1~5점)를 부여하세요.
        
        - Buzz 데이터: {stock_data.get('recent_posts_count', 0)} posts
        - AI 감정 요약: {stock_data.get('posts_summary', '정보 없음')}
        - 외인 수급: {stock_data.get('foreign_rate', '0%')} (전일: {stock_data.get('prev_foreign_rate', '0%')})
        - 키워드: {stock_data.get('keywords', [])}
        
        **평가 항목:**
        1) Buzz 가속도: 글 수의 증가세가 가파른가?
        2) 여론의 질: 단순 도배가 아닌 실질적 호재나 분석글이 많은가?
        3) 외인 수합: 외국인이 매집 중인가?
        4) 추세 위치: 현재가가 과열권인가, 아니면 반전의 시작인가?
        
        **출력 형식 (JSON 전용):**
        {{
            "score": 1~5점 정수,
            "reason": "항목별 근거 요약"
        }}
        """
        try:
            # 안전 호출 (Double Defense 적용)
            response = self.gemini._call_gemini_safe(prompt, generation_config={"response_mime_type": "application/json"})
            if response and response.text:
                result = json.loads(response.text)
                return result.get('score', 2), result.get('reason', '평가 실패')
        except: pass
        return 2, "AI 분석 엔진 오류"

    def execute_strategy(self, candidates):
        """
        [Algorithm] 점수에 따른 차등 배분
        5점: 40%, 4점: 20%, 3점: 5%, 2점 이하: 탈락
        """
        if not candidates: return
        
        total_cash = self.state['cash'] + self.state['invested']
        
        for stock in candidates[:10]: # 상위 10개 후보만 평가
            code = stock['code']
            if code in self.state['portfolio']: continue # 이미 보유 중이면 패스
            
            score, reason = self.assess_conviction(stock)
            
            # 비중 계산
            weight = 0
            if score == 5: weight = 0.40
            elif score == 4: weight = 0.20
            elif score == 3: weight = 0.05
            
            if weight > 0:
                price = float(stock.get('price', 0))
                if price <= 0: continue
                
                target_amount = total_cash * weight
                # 현재 예수금 내에서 가능한 만큼만 매수
                buy_amount = min(self.state['cash'] * 0.95, target_amount)
                qty = int(buy_amount / price)
                
                if qty > 0:
                    self.buy(code, stock['name'], price, qty, reason=f"Sim 2 (Score {score}): {reason}")

    def check_liquidation(self, current_stocks):
        """
        [Dynamic Exit] 15분 주기 재평가 및 청산
        - 점수가 2점 이하로 하락하거나 T+2일 경과 시 즉시 청산
        """
        today = datetime.datetime.now()
        to_sell = []
        
        for code, item in self.state['portfolio'].items():
            # 1. 시간 기반 청산 (T+2)
            buy_date = datetime.datetime.strptime(item['buy_date'], '%Y-%m-%d')
            if (today - buy_date).days >= 2:
                to_sell.append((code, "T+2 시간 청산"))
                continue
                
            # 2. 점수 기반 청산 (재평가)
            # current_stocks에서 해당 종목 정보 찾기
            stock_data = next((s for s in current_stocks if s['code'] == code), None)
            if stock_data:
                score, reason = self.assess_conviction(stock_data)
                if score <= 2:
                    to_sell.append((code, f"AI 점수 하락 청산 ({score}점): {reason}"))
            
        for code, reason in to_sell:
            # 현재가 탐색 로직 (단순화: current_stocks에서 가져옴)
            stock_info = next((s for s in current_stocks if s['code'] == code), None)
            if stock_info and float(stock_info.get('price', 0)) > 0:
                self.sell(code, float(stock_info['price']), reason=reason)
