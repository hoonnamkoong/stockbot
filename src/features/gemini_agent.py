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
            self.model_name = 'gemini-2.5-flash'
            self.model = genai.GenerativeModel(self.model_name)
            self.fallback_models = ['gemini-2.0-flash', 'gemini-2.5-flash-lite']
            print(f"[GeminiAgent] Initialized with {self.model_name}")
        except Exception as e:
            print(f"[GeminiAgent] Initialization Error: {e}")
            self.model = None

    def _generate_content_safe(self, prompt):
        """
        Attempts to generate content with the current model.
        If it fails (404 or 400), retries with fallback models.
        """
        if not self.model:
            raise Exception("Model not initialized")

        # List of models to try: Current -> Fallback 1 -> Fallback 2
        models_to_try = [self.model_name] + self.fallback_models
        
        last_error = None

        for model_name in models_to_try:
            try:
                # Re-configure model if switching
                if model_name != self.model_name:
                    print(f"[GeminiAgent] Switching to fallback model: {model_name}")
                    self.model = genai.GenerativeModel(model_name)
                    self.model_name = model_name

                response = self.model.generate_content(prompt)
                return response
            except Exception as e:
                error_str = str(e)
                # Catch 404 (Not Found) or 400 (Invalid Argument/Bad Request)
                if "404" in error_str or "not found" in error_str.lower() or "400" in error_str:
                    print(f"[GeminiAgent] Model {model_name} failed: {e}")
                    last_error = e
                    continue # Try next model
                else:
                    # If it's another error (e.g. quota, auth), fail immediately
                    raise e
        
        raise last_error

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
            response = self._generate_content_safe(prompt)
            # Basic cleanup in case Gemini returns markdown blocks
            text = response.text.replace('```json', '').replace('```', '').strip()
            
            # Simple simulation of parsing (In production, use json.loads)
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
            response = self._generate_content_safe(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"[GeminiAgent] Risk Assessment Error: {e}")
            return f"AI 분석 오류: {str(e)[:50]}..." 

    def generate_trading_guide(self, market_data):
        """
        Generates a 'Stock Investment Expert' style trading guide based on the collected market data.
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
        당신은 20년 경력의 주식 매매 전문가입니다. 아래는 오늘 한국 주식시장에서 커뮤니티 토론이 폭발하고 있는 종목 리스트입니다.

        [오늘의 스크래핑 데이터]
        {data_str}

        [미션]
        위 종목 중 **매매 액션이 필요한 종목만 골라서** 구체적인 매매 전략을 제시하세요.
        모든 종목을 나열하지 마세요. 주목할 만한 종목만 선별하여 분석하세요.

        [작성 원칙]
        1. **매매 전략 우선**: 매수/매도/관망 중 어떤 액션을 취해야 하는지 먼저 제시
        2. **판단 근거**: 왜 그런 판단을 했는지 키워드와 토론 내용에서 추론한 근거를 설명
        3. **구체적 조건**: 목표가, 손절가, 진입 타이밍 등 실행 가능한 조건 제시
        4. **간결하게**: 텔레그램 메시지로 보내기 적합한 길이 (종목당 2~3줄)

        [출력 양식]
        🎯 **[매매 가이드]**

        📌 **종목명** | 액션: 매수/매도/관망
        → 판단 근거 (1줄)
        → 전략: 구체적 매매 조건 (1줄)

        📌 **종목명** | 액션: 매수/매도/관망
        → 판단 근거 (1줄)
        → 전략: 구체적 매매 조건 (1줄)

        ⚠️ **[오늘의 리스크]**
        (시장 전반적 과열/급락 경고가 있다면 1~2줄로 간결하게)
        """

        try:
            response = self._generate_content_safe(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"[GeminiAgent] Guide Generation Error: {e}")
            return f"AI 분석 중 오류가 발생했습니다. (사유: {str(e)[:100]})"

