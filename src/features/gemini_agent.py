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
            self.model = genai.GenerativeModel('gemini-pro')
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
        for stock in market_data[:10]: # Analyze top 10 trends
            simplified_data.append(f"- {stock.get('name')} ({stock.get('change_rate')}): {stock.get('top_keywords', '')}")
        
        data_str = "\n".join(simplified_data)

        prompt = f"""
        당신은 20년 경력의 주식 투자 전문가(Stock Investment Expert)입니다.
        아래는 현재 시장에서 가장 화제가 되고 있는 급등주와 관련 키워드입니다.

        [시장 데이터]
        {data_str}

        [요청 사항]
        위 데이터를 바탕으로 투자자들을 위한 **실전 매매 가이드**를 작성해주세요.
        
        [작성 원칙]
        1. **전문가적 어조**: 신뢰감 있고 분석적인 톤을 유지하세요. (예: "~것으로 판단됩니다.", "~주시할 필요가 있습니다.")
        2. **핵심 위주**: 장황한 설명보다 핵심 섹터나 테마를 짚어주세요.
        3. **구조화된 출력**:
           - 📊 **시장 트렌드 요약**: 현재 시장을 주도하는 테마가 무엇인지 한 줄 요약
           - 💡 **주요 섹터 분석**: 상승세를 보이는 업종이나 이슈 분석
           - ⚠️ **투자 유의사항**: 추격 매수 자제나 리스크 관리 조언
        4. **분량**: 500자 이내로 핵심만 전달하세요.
        5. **언어**: 한국어(Korean)로 작성하세요.

        출력 예시:
        📊 **[시장 트렌드] 바이오주 강세 지속**
        금일 시장은 OO 이슈로 인해 바이오 섹터가 강한 수급을 보이고 있습니다...
        """

        try:
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"[GeminiAgent] Guide Generation Error: {e}")
            return "AI 분석 중 오류가 발생했습니다."

