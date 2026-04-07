import json
import os
import datetime
import re
from .base_simulator import BaseSimulator
from src.strategy.advisor import StrategyAdvisor, GeminiAgent

class ConvictionSimulator(BaseSimulator):
    """
    [Sim 3] 컨빅션 전략 (AI 확신도 기반)
    - GeminiAgent를 통해 1차 통과 종목에 확신도 점수(1~5) 부여
    - 점수에 따라 투자 비중 차등 배분 (5점: 100%, 4점: 80%, 3점: 60% ...)
    - 매매 시 100자 내외의 AI 판단 사유를 CSV 로그에 영구 기록
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("Conviction", initial_cash)
        self.gemini = GeminiAgent()

    def assess_conviction(self, stock):
        """
        [AI Logic] 종목의 모멘텀과 Buzz를 바탕으로 확신도 점수 산출
        """
        if not self.gemini.model: return 3, "AI 서비스 일시 중단 - 기본 비중 관망"
        
        prompt = f"""
        종목: {stock.get('name')} ({stock.get('code')})
        현재 수급: {stock.get('recent_posts_count')} posts (기준치 돌파)
        AI 요약: {stock.get('posts_summary')}
        키워드: {', '.join(stock.get('keywords', []))}
        
        위 데이터를 바탕으로 이 종목의 단기 상승 확신도를 1~5점(5점 만점)으로 평가하고,
        그 이유를 100자 내외의 전문적인 '컨빅션 메시지'로 작성하세요.
        
        반드시 다음 JSON 형식으로만 답변하세요:
        {{
            "score": 점수,
            "reason": "컨빅션 메시지"
        }}
        """
        try:
            response = self.gemini._call_gemini_safe(
                prompt, 
                generation_config={"response_mime_type": "application/json"}
            )
            if response and response.text:
                res = json.loads(response.text)
                return int(res.get('score', 3)), str(res.get('reason', '관망 추천'))
        except: pass
        return 3, "분석 시스템 지연 - 보수적 접근"

    def execute_strategy(self, candidates):
        if not candidates: return
        
        # 상위 5개 종목에 대해 컨빅션 분석 수행
        for stock in candidates[:5]:
            code = stock['code']
            if code in self.state['portfolio']: continue
            
            score, reason = self.assess_conviction(stock)
            
            # 확신도 4점 이상만 진입 (엄격한 필터링)
            if score >= 4:
                # 점수에 따른 종목당 목표 비중 (최대 10종목 기준 균등의 N배)
                # 5점: 자산의 30%, 4점: 자산의 20%
                target_ratio = 0.3 if score == 5 else 0.2
                target_amount = (self.initial_cash + self.state['invested']) * target_ratio
                
                price = float(stock.get('price', 0))
                if price <= 0: continue
                
                qty = int(target_amount / price)
                if qty > 0:
                    # CSV 로그에 AI 판단 사유(reason)가 포함됨
                    full_reason = f"[컨빅션 {score}점] {reason}"
                    self.buy(code, stock['name'], price, qty, reason=full_reason)
                    print(f"[Sim 3] {stock['name']} AI 매수 (점수: {score})")

    def check_liquidation(self, candidates_codes):
        """
        [AI Exit] 보유 종목의 Buzz 이탈 또는 AI 판단 변화 시 청산
        """
        codes = list(self.state['portfolio'].keys())
        for code in codes:
            # 1. 1차 필터(Buzz) 이탈 시 우선 청산
            if code not in candidates_codes:
                p_item = self.state['portfolio'][code]
                self.sell(code, p_item['price'], reason="[컨빅션] Buzz 모멘텀 이탈로 인한 자동 청산")
                continue
            
            # 2. 보유 종목이 여전히 매수 등급인지 Gemini에게 가끔 재확인 (재평가 로직 추가 가능)
            pass
