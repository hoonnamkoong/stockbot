import google.generativeai as genai
import os
from src.core.config import GEMINI_KEY

class GeminiAgent:
    """
    Agent responsible for cross-validating market signals using Gemini.
    """
    def __init__(self):
        if not GEMINI_KEY:
            print("[GeminiAgent] WARNING: API Key not found!")
            self.model = None
            return

        try:
            genai.configure(api_key=GEMINI_KEY)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
            print("[GeminiAgent] Initialized successfully.")
        except Exception as e:
            print(f"[GeminiAgent] Initialization Error: {e}")
            self.model = None

    def cross_validate(self, symbol, keywords):
        """
        Asks Gemini if the current buzz around 'symbol' with 'keywords' 
        is based on substantial news/disclosure.
        """
        if not self.model:
            return {'status': 'ERROR', 'reason': 'No API Key'}

        prompt = f"""
        You are a strict financial risk manager.
        
        Target Stock: {symbol}
        Trending Keywords: {', '.join(keywords)}

        Task:
        Analyze if there is ANY confirmed disclosure (Data/News) backing this trend.
        
        Rules:
        1. If verified news (M&A, Contract, Earnings, Gov Policy) exists -> Return APPROVED
        2. If it is just rumors, noise, or community hype -> Return REJECTED
        3. If uncertain -> Return PASS

        Output Format (JSON only):
        {{
            "status": "APPROVED" | "REJECTED" | "PASS",
            "reason": "One sentence explanation."
        }}
        """
        
        try:
            response = self.model.generate_content(prompt)
            # Basic cleanup in case Gemini returns markdown blocks
            text = response.text.replace('```json', '').replace('```', '').strip()
            
            # Simple simulation of parsing (In production, use json.loads)
            # Here we trust Gemini's string output, or fallback
            if "APPROVED" in text:
                reason = text.split('"reason":')[1].strip().strip('"}') if '"reason":' in text else "Gemini Approved"
                return {'status': 'APPROVED', 'reason': reason}
            else:
                return {'status': 'PASS', 'reason': "Gemini did not find strong evidence."}

        except Exception as e:
            print(f"[GeminiAgent] Generation Error: {e}")
            return {'status': 'ERROR', 'reason': str(e)}

    def generate_risk_assessment(self, symbol, signal_type, technical_reason, keywords, summary):
        """
        Generates a concise expert opinion for a sell/buy signal.
        Target length: 1-2 sentences.
        """
        if not self.model:
            return "AI 모델 오류: 키 생성 실패"

        prompt = f"""
        당신은 냉철한 주식 트레이딩 멘토입니다.
        현재 '{symbol}' 종목에 대해 기술적 매도/매수 신호가 발생했습니다.
        
        [신호 정보]
        - 종목명: {symbol}
        - 신호유형: {signal_type}
        - 기술적 사유: {technical_reason}
        - 주요 키워드: {keywords}
        - 토론방 요약: {summary}

        [미션]
        이 신호에 대해 투자자에게 줄 **한 줄 코멘트(Opinion)**를 작성하세요.
        단순히 신호를 반복하지 말고, 토론방 분위기나 키워드를 통해 **"왜"** 이 신호가 떴는지, **"어떻게"** 대응해야 하는지 직관적으로 조언하세요.
        
        [작성 원칙]
        1. **1-2문장**으로 짧게 작성 (텔레그램 알림용)
        2. 비꼬거나 부정적인 말투 금지, 전문가적이고 건조하게.
        3. **구체적 근거** 언급 (예: "신성델타테크 퀀텀 소식으로 인한 급등 피로감...")
        4. 분할 매도/매수 등 **행동 지침** 포함.

        [예시]
        (매도 신호) "태양광 섹터 전반적 조정 분위기이며, 구체적 악재보다는 단기 급등에 따른 차익 실현 물량으로 판단됩니다. 분할 매도로 수익 보존을 권장합니다."
        """

        try:
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"[GeminiAgent] Risk Assessment Error: {e}")
            return f"AI 분석 오류: {str(e)[:50]}..." # Show partial error for debugging

    def generate_trading_guide(self, market_data):
        """
        Generates a 'Stock Investment Expert' style trading guide based on the collected market data.
        
        Args:
            market_data (list): List of dictionaries containing stock info (name, change_rate, keywords, etc.)
        
        Returns:
            str: A structured analysis string in Korean.
        """
        if not self.model:
            return "AI 모델이 초기화되지 않아 분석을 제공할 수 없습니다."

        # Simplify data for prompt to save tokens
        simplified_data = []
        for stock in market_data[:15]: # Analyze top 15 trends
            summary = stock.get('posts_summary', '내용 없음')
            keywords = stock.get('top_keywords', '')
            simplified_data.append(f"- {stock.get('name')} ({stock.get('change_rate')}): {keywords} | 요약: {summary}")
        
        data_str = "\n".join(simplified_data)

        prompt = f"""
        당신은 20년 경력의 주식 투자 전문가(Senior Stock Analyst)입니다.
        아래는 현재 한국 시장(KOSPI/KOSDAQ)에서 개인 투자자들의 관심이 폭발하고 있는 급등주들의 커뮤니티 토론 요약입니다.

        [시장 데이터]
        {data_str}

        [목표]
        이 데이터를 바탕으로 투자자들에게 **실질적인 매매 가이드**와 **상승 원인 분석**을 제공하세요.
        단순히 "매도하세요"라고 하지 말고, **왜** 그런지, **어떤 뉴스/이슈**가 있는지(키워드로 추론) 설명해야 합니다.

        [작성 원칙]
        1. **심층 분석**: 키워드와 토론 요약을 통해 **상승의 재료(News/Material)**를 추론하십시오. (예: 'FDA', '임상' -> 바이오 호재 / '계약' -> 수주 공시 추정)
        2. **섹터/테마 연결**: 개별 종목 나열보다 "바이오 섹터 강세", "정치 테마주 순환매" 등으로 묶어서 설명하세요.
        3. **구체적 가이드**: 추격 매수 금지, 분할 매도, 지지선 확인 등 구체적인 액션을 제안하세요.
        4. **참조 자료(Reference)**: 분석의 근거가 되는 이슈(공시, 뉴스 키워드 등)를 명시하세요.

        [출력 양식]
        📊 **[시장 주도 테마]**
        (현재 시장을 이끄는 핵심 테마와 그 배경 1~2줄)

        💡 **[주요 섹터 및 이슈 분석]**
        - **[종목/테마명]**: (상승 원인 분석. 예: "삼천당제약은 오늘 아일리아 시밀러 계약 이슈로 급등...")
        - **[종목/테마명]**: (분석 내용...)

        🗞 **[뉴스 & 재료 체크]**
        (키워드로 파악된 주요 공시나 뉴스가 있다면 언급. 불확실하면 "단순 수급 쏠림"으로 표기)

        🛑 **[투자 전략 & 유의사항]**
        (단기 과열 경고, 대응 전략, 손절 원칙 등 전문가적 조언)
        """

        try:
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"[GeminiAgent] Guide Generation Error: {e}")
            return f"AI 분석 중 오류가 발생했습니다. (사유: {str(e)[:100]})"

