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
