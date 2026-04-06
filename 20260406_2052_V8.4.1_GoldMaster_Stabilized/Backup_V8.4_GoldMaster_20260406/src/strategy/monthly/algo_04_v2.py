import math
import json
from src.strategy.base import BaseStrategy

class Algo04V2(BaseStrategy):
    """
    [V2 Strategy Module] 4월 어텐션 모멘텀 알고리즘 명세.
    지시사항: 어떠한 API 호출이나 I/O 없이 파라미터로 받은 데이터로만 계산합니다.
    """
    def __init__(self):
        self.MAX_ALLOC_PER_STOCK = 600000 # 종목당 최대 60만원
        self.MIN_ENTRY_CASH = 100000      # 최소 진입 가능 예수금

    def analyze_target(self, stock_data, dart_data, llm_decision, current_cash):
        """
        [지시사항 1, 3, 5] 1차 필터 + 2차 검증 + AI 승인 + 포지션 사이징 결합
        """
        # 1. 1차 매수 필터 (AND 조건)
        try:
            p_change = float(str(stock_data.get('change_rate', 0.0)).replace('%', ''))
        except: p_change = 0.0
            
        post_count = int(stock_data.get('post_count', 0))
        positive_rate = float(stock_data.get('positive_rate', 0.0))
        foreign_rate_diff = float(stock_data.get('foreign_rate_diff', 0.0))
        current_price = float(stock_data.get('price', 0))

        cond1 = post_count >= 100
        cond2 = positive_rate >= 60.0
        cond3 = foreign_rate_diff > 0.0
        cond4 = 5.0 < p_change < 20.0

        if not (cond1 and cond2 and cond3 and cond4):
            return {"action": "WATCH", "reason": "1차 필터(AND) 조건 미충족"}

        # 2. 2차 검증 오버레이 (DART & NEWS 결과)
        if dart_data.get('reject'):
            return {"action": "WATCH", "reason": f"DART 거부됨: {dart_data['reason']}"}
        
        # 3. Gemini V2 최종 승인 여부
        if llm_decision.get("decision") != "APPROVED":
            return {"action": "WATCH", "reason": "AI 모멘텀 승인 거부"}

        # 4. [지시사항 3, 5] 포지션 사이징 및 수량 계산 (버그 수정본)
        # 예수금 부족 시 유연하게 할액 결정 (마이너스 잔고 방지)
        
        if current_cash < self.MIN_ENTRY_CASH:
            return {"action": "WATCH", "reason": f"예수금 부족 (보유: {current_cash:,.0f}원)"}
            
        # [Rule] 60만원 한도 내에서, 잔액이 부족하면 남은 전액을 할당
        alloc_amount = min(self.MAX_ALLOC_PER_STOCK, current_cash)
        
        if current_price <= 0:
            return {"action": "WATCH", "reason": "가격 데이터 오류"}

        quantity = math.floor(alloc_amount / current_price)
        
        if quantity <= 0:
            return {"action": "WATCH", "reason": "매수 가능 수량이 0주입니다."}

        return {
            "action": "BUY", 
            "quantity": quantity, 
            "reason": llm_decision.get("telegram_narrative", "어텐션 모멘텀 강력"),
            "alloc_amount": alloc_amount
        }

    def check_exit_signal(self, holding_data, stock_data, prev_post_count):
        """
        [지시사항 4] V2 매도 룰 (Adaptive Exit)
        """
        current_price = float(stock_data.get('price', 0))
        avg_price = float(holding_data.get('average_buy_price', 0))
        current_post_count = int(stock_data.get('post_count', 0))
        
        if avg_price <= 0: return {"action": "HOLD", "reason": "기준가 없음"}
        
        profit_rate = ((current_price - avg_price) / avg_price) * 100.0
        
        # 1) 하드스탑: 수익률 <= -5.0%
        if profit_rate <= -5.0:
            return {"action": "SELL_ALL", "reason": f"🚨 하드스탑 탈출 (수익률: {profit_rate:.2f}%)"}
            
        # 2) 50% 분할 익절: 수익률 >= +10.0%
        if profit_rate >= 10.0:
            return {"action": "SELL_HALF", "reason": f"⚠️ 50% 분할 익절 (+10% 목표 도달)"}

        # 3) 어텐션 소멸: 어제 대비 post_count가 -50% 이상 감소
        if prev_post_count > 0:
            decay_rate = ((current_post_count - prev_post_count) / prev_post_count) * 100.0
            if decay_rate <= -50.0:
                return {"action": "SELL_ALL", "reason": f"📉 어텐션 소멸 ({decay_rate:.1f}%)"}

        return {"action": "HOLD", "reason": f"보유 유지 (수익률: {profit_rate:.2f}%)"}
