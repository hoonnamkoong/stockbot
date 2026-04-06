from abc import ABC, abstractmethod

class BaseStrategy(ABC):
    """
    [V2 Architecture] 모든 월별 투자 전략의 최상위 인터페이스.
    이 클래스는 어떠한 API 호출이나 파일 I/O도 수행하지 않는 '순수 논리' 규격입니다.
    """

    @abstractmethod
    def analyze_target(self, stock_data, dart_data, llm_decision, current_cash):
        """
        신규 매수 진입 여부를 판단합니다.
        
        Args:
            stock_data (dict): post_count, positive_rate, change_rate 등 지표
            dart_data (dict): DART 공시 분석 결과 (reject 여부 등)
            llm_decision (dict): Gemini의 최종 APPROVED/REJECTED 여부
            current_cash (int): 현재 시뮬레이션 가용 예수금
            
        Returns:
            dict: {"action": "BUY", "quantity": N, "reason": "..."} 또는 {"action": "WATCH"}
        """
        pass

    @abstractmethod
    def check_exit_signal(self, holding_data, stock_data, prev_post_count):
        """
        보유 종목의 매도 신호를 점검합니다 (Adaptive Exit).
        
        Args:
            holding_data (dict): 평단가, 보유 수량 등 포트폴리오 정보
            stock_data (dict): 현재가, 당일 어텐션 지표 등
            prev_post_count (int): 어제 자 게시글 수
            
        Returns:
            dict: {"action": "SELL_ALL" | "SELL_HALF" | "HOLD", "reason": "..."}
        """
        pass
