import json
import datetime

class StrategyEngine:
    """
    Pure Logic Engine for Stock Scoring and Signal Generation.
    Hybrid Engine (March + April V2 Adaptive Attention Momentum)
    NO external API calls (KIS, Google, etc.) allowed here.
    """
    def __init__(self, config=None):
        self.config = config or {}

    def calculate_score(self, stock_data):
        """
        1차 관문 필터링 모듈
        기존 점수 방식 대신 4대 팩터(AND 조건)를 만족하는지 검사합니다.
        
        stock_data: dict containing:
        - post_count (int): 당일 게시글 수
        - positive_rate (float): 감정분석 Positive 비율 (0.0 ~ 100.0)
        - foreign_rate_diff (float): 전일 대비 외국인 비중 변화
        - change_rate (str 또는 float): 당일 주가 등락률
        """
        try:
            p_change = stock_data.get('change_rate', 0.0)
            if isinstance(p_change, str):
                p_change = float(p_change.replace('%', ''))
        except:
            p_change = 0.0
            
        post_count = int(stock_data.get('post_count', 0))
        positive_rate = float(stock_data.get('positive_rate', 0.0))
        foreign_rate_diff = float(stock_data.get('foreign_rate_diff', 0.0))

        # 4대 팩터 검사
        is_attention_high = post_count >= 100
        is_sentiment_good = positive_rate >= 60.0
        is_smart_money_in = foreign_rate_diff > 0.0
        has_upside_room = 5.0 < p_change < 20.0

        score = 0 # 의미상 더 이상 점수를 쓰진 않지만 하위 호환성을 위해 유지
        if is_attention_high and is_sentiment_good and is_smart_money_in and has_upside_room:
            score = 100 # 통과
            
        return score, p_change

    def get_signal(self, score, p_change, in_portfolio=False, profit_rate=0.0, post_count_diff_pct=0.0, positive_rate=50.0):
        """
        Determines the signal based on 4월 V2 매수 및 인공지능 매도 룰.
        
        post_count_diff_pct: 어제 대비 당일 게시글 수 증감률 (%)
        """
        signal = "WATCH"
        confidence = "LOW"
        
        # 1. 미보유 종목 처리 (신규 매수 진입 룰)
        if not in_portfolio:
            if score == 100:
                signal = "BUY_CANDIDATE"
                confidence = "HIGH"
            return signal, confidence
            
        # 2. 보유 종목 처리 (Adaptive Exit Rules - 인공지능형 출구 전략)
        
        # [2-1. 칼날 손절 (Hard Stop)]
        if profit_rate <= -5.0:
            signal = "SELL_ALL"
            confidence = "HIGH"
            reason = "Hard Stop (-5.0% Risk Cut)"
            return signal, confidence
            
        # [2-2. 50/50 익절 (Scale-out)]
        if profit_rate >= 10.0:
            # V2 룰에서는 한번 +10% 쳤을 때 절반 매도 처리.
            # 이 로직을 위해서는 이미 50%를 덜어냈는지 확인해야 하지만, 상태 저장은 외부에서 하므로 일단 SELL_HALF 반환
            signal = "SELL_HALF"
            confidence = "HIGH"
            return signal, confidence

        # [2-3. 어텐션 소멸 탈출 (Attention Decay)]
        if post_count_diff_pct <= -50.0 or positive_rate < 50.0:
            signal = "SELL_ALL"
            confidence = "MEDIUM"
            return signal, confidence

        # [2-4. 어텐션 가속도 홀딩 (Velocity Hold)]
        signal = "HOLD"
        confidence = "HIGH"
        return signal, confidence
