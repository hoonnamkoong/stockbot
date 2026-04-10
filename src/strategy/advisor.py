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
    [V8.6.0] Fixed Gemini Engine & Singleton Controller
    - 싱글톤 패턴으로 인스턴스 중복 생성 방지
    - 모델 하드코딩 (Batch: Flash-Lite, Report: Pro)
    - 429 발생 시 즉시 중단 (Fail-Fast)
    """
    _instance = None
    exhausted_models = set() # 429(Daily) 발생 모델 기록

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GeminiAgent, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    @staticmethod
    def clean_text(text):
        if not text: return ""
        # ㅋㅋ, ㅎㅎ, ㅠㅠ 등 3번 이상 반복되는 자모음 압축
        text = re.sub(r'([ㄱ-ㅎㅏ-ㅣ])\\1{2,}', r'\\1', text)
        # 불필요한 특수문자 여러개 압축
        text = re.sub(r'([!?.~])\\1{2,}', r'\\1', text)
        # 여러개 공백을 하나로 압축
        text = re.sub(r'\s+', ' ', text)
        return text.strip()[:200]

    def __init__(self):
        if self._initialized: return
        
        # [V8.6.0] 모델 명칭 선설정 (API 키 부재 시에도 속성 참조 가능하도록 보장)
        self.batch_model_name = "models/gemini-2.0-flash"
        self.report_model_name = "models/gemini-2.0-flash"
        self.exhausted_models = set() if not hasattr(self, 'exhausted_models') else self.exhausted_models

        self.api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_KEY')
        
        if not self.api_key:
            print("[GeminiAgent] 🚨 에러: API 키가 감지되지 않습니다. 모델은 초기화되지 않았습니다.")
            self.batch_model = None
            self.report_model = None
            self._initialized = True # 반복 에러 방지
            return

        genai.configure(api_key=self.api_key)
        
        # [V8.6.0] 모델 고정 (유료 티어 성능 100% 활용)
        self.batch_model = genai.GenerativeModel(self.batch_model_name)
        self.report_model = genai.GenerativeModel(self.report_model_name)
        
        self._initialized = True
        print(f"[GeminiAgent] ✅ V8.6.0 싱글톤 엔진 가동 (Lite & Pro Fixed)")

    # [V8.6.0] 동적 모델 업데이트 로직 폐기 (Fixed Engine 체제)

    def _call_gemini_safe(self, prompt, model_type='batch', generation_config=None):
        """
        [V8.6.0 Fail-Fast] 고정 모델 체제. 429 발생 시 즉시 중단 및 블랙리스트 등록
        model_type: 'batch' (Flash-Lite) or 'report' (Pro)
        """
        target_model = self.batch_model if model_type == 'batch' else self.report_model
        target_name = self.batch_model_name if model_type == 'batch' else self.report_model_name
        
        if target_name in self.exhausted_models:
            print(f"[GeminiAgent] ⛔ {target_name}은 쿼터 소진으로 인해 호출 불가 상태입니다.")
            return None

        try:
            return target_model.generate_content(prompt, generation_config=generation_config)
        except Exception as e:
            err_msg = str(e)
            if ("429" in err_msg or "Quota" in err_msg or "ResourceExhausted" in err_msg):
                print(f"[GeminiAgent] 🚨 Quota Exceeded ({target_name}). 즉시 분석 중단 및 블랙리스트 등록.")
                self.exhausted_models.add(target_name)
            else:
                print(f"[GeminiAgent] 🚨 API 에러 ({target_name}): {err_msg}")
        
        return None

    def generate_trading_guide(self, market_context, signals):
        """[V8.4.6] 31개 종목 누락 방지 및 딥다이브 리포트 생성"""
        if not self.report_model: return "⚠️ Gemini API 초기화 실패: 리포트를 생성할 수 없습니다."
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
        
        [V8.6.1 리포트 초간결화(Brevity) 절대 규칙]
        1. 모든 내용은 불렛포인트(•)로 시작하며 핵심 키워드 위주의 단답형으로 기술한다.
        2. "~임", "~함" 등 명사형으로 종결하며 서술어(입니다, 판단됩니다 등)를 전면 제거한다.
        3. 섹션당 불렛포인트는 최대 3개를 넘지 않는다.
        4. 핵심 재료와 수급 주체는 반드시 **두꺼운 글씨(Bold)**를 사용한다.
        5. '가즈아', '무조건' 등 게시판 노이즈는 무시하고 팩트만 남긴다.

        [시장상황] {market_context}
        [데이터] {json.dumps(cleaned_signals, ensure_ascii=False)}
        
        **출력 가이드:**
        1. [Top 3 대장주]: 선정 이유를 핵심 키워드 중심(•)으로 기술.
        2. [주의 리스크]: 리스크가 없을 경우 단 한 줄 "• **특이사항 없음**"으로 끝낼 것.
        3. 마크다운(**) 외 HTML 태그는 절대 사용 금지.
        """
        try:
            response = self._call_gemini_safe(prompt, model_type='report')
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
        if not self.batch_model: return "WATCH"
        
        prompt = f"""
        종목명: {stock.get('name')} ({stock.get('code')})
        현재 Buzz: {stock.get('post_count')} posts
        최근 뉴스: {news}
        공시 분석: {dart}
        
        [V8.6.0 노이즈 필터] 단순 선동이나 감정적 글은 무시하고 팩트 위주로 모멘텀을 평가하세요.

        위 데이터를 바탕으로 이 종목의 단기 모멘텀을 평가하세요.
        """
        try:
            response = self._call_gemini_safe(prompt, model_type='batch')
            return response.text.strip() if response and response.text else "WATCH"
        except:
            return "WATCH"

    def analyze_batch_discovery(self, batch_data):
        """
        [V8.5.5] 1차 필터 통과 종목군 일괄 분석 (Batch Discovery)
        - 한 번의 API 호출로 모든 종목의 감정/요약/키워드 추출
        - Quota 절감 및 분석 속도 개선
        """
        if not self.batch_model or not batch_data: 
            return {s.get('code', s.get('name')): {"sentiment_score": 0, "summary": "AI 분석 불가", "keywords": []} for s in batch_data}
        
        # [V8.9.9.6] 데이터 경량화 및 정합성 보전 (Body 일부 포함하여 분석 품질 향상)
        # 종목 수가 많을 경우 10개씩 그룹화하여 API 호출
        GROUP_SIZE = GroupSize = 10
        all_results = {}
        
        for i in range(0, len(batch_data), GROUP_SIZE):
            group = batch_data[i:i + GROUP_SIZE]
            cleaned_batch = []
            for stock in group:
                # 추천수가 높은 본문(Body)을 요약에 활용 (글자 수 제한 준수)
                posts_text = "\n".join([f"[{p.get('title')}] {GeminiAgent.clean_text(str(p.get('body', '')))}" for p in stock.get('posts', [])])
                cleaned_batch.append({
                    "code": stock.get('code'),
                    "name": stock.get('name'),
                    "content": posts_text
                })
            
            # 그룹별 프롬프트 생성 및 호출
            prompt = f"""
            당신은 주식 종목 토론방의 대중 심리와 팩트를 분석하는 전문가입니다.
            아래 리스트({len(cleaned_batch)}개 종목)의 데이터를 분석하여 결과를 도출하세요.

            [V8.6.1 분석 규칙 - 절대 준수]
            1. 선동/감탄사(가즈아 등)는 무조건 0점 처리하고 summary에 '노이즈' 표기.
            2. summary는 10자 이내 2~3단어 초간결 명사형 요약. (예: 신사업기대감, 외인매수)
            3. keywords는 2개 이내 핵심 단어만 추출.

            [분석 대상 데이터]
            {json.dumps(cleaned_batch, ensure_ascii=False)}
            
            각 종목별로 종목코드(code)를 Key로 사용하여 다음 JSON 형식으로만 응답하세요:
            {{
                "005930": {{
                    "sentiment": 점수(-10 ~ 10),
                    "summary": "초간결 명사 요약",
                    "keywords": ["키워드1", "키워드2"]
                }}
            }}
            """
            try:
                response = self._call_gemini_safe(
                    prompt,
                    model_type='batch',
                    generation_config={"response_mime_type": "application/json"}
                )
                if response and response.text:
                    raw_text = response.text.strip()
                    if raw_text.startswith("```"):
                        raw_text = re.sub(r"^(?:```[a-z]*\n)|(?:```$)", "", raw_text, flags=re.MULTILINE).strip()
                    parsed = json.loads(raw_text)
                    # [V8.9.9.9 Fix] 파싱 결과가 list일 경우 dict로 변환 (Gemini 응답 변동성 대응)
                    if isinstance(parsed, list):
                        parsed = {item.get('code', str(i)): item for i, item in enumerate(parsed) if isinstance(item, dict)}

                    # [V8.9.9.5 Fix] 파싱 결과가 반드시 dict여야 함 (문자열 오인 방지)
                    if isinstance(parsed, dict):
                        all_results.update(parsed)
                    else:
                        print(f"[GeminiAgent] 응답이 dict가 아님, 스킵: {type(parsed)}")
            except Exception as e:
                print(f"[GeminiAgent] Group Batch 분석 오류 ({i//GROUP_SIZE + 1}번 그룹): {e}")

        # 분석 실패한 종목들에 대한 기본값 처리
        final_results = {}
        for s in batch_data:
            code = s.get('code')
            final_results[code] = all_results.get(code, {"sentiment": 0, "summary": "분석 오류", "keywords": []})
            
        return final_results

    def analyze_bulk_sentiment(self, bulk_data):
        """기존 벌크 감성 분석 로직 유지 (모델 동적 적용)"""
        if not self.batch_model: return {}
        try:
            processed_bulk = []
            for s in bulk_data:
                processed_bulk.append({
                    "code": s.get('code'),
                    "name": s.get('name'),
                    "bodies": [str(b)[:300] for b in s.get('bodies', [])]
                })

            prompt = f"다음 주식 종목들의 토론방 분위기를 분석하여 감성 점수(-10 ~ 10)를 JSON 형식으로만 답변하세요:\n{json.dumps(processed_bulk, ensure_ascii=False)}"
            
            response = self._call_gemini_safe(
                prompt,
                model_type='batch',
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
        """[V8.4.7] 개장일 중심 리포트 생성 로직 (Legacy)"""
        all_results = self.engine.execute_simulation(candidates, allow_buy=allow_buy)
        market_context = f"{len(candidates)}개 종목 Buzz 필터 통과. 시장 주도 섹터 및 모멘텀 분석."
        gemini_guide = self.gemini.generate_trading_guide(market_context, candidates)
        summary = f"\n---\n📊 **V8.4.7 Gold Master 시스템 리포트**\n"
        summary += f"📅 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        buy_targets = [r for r in all_results if r.get('signal') == 'BUY']
        if buy_targets:
            summary += f"🔥 매수 대상: {', '.join([t['name'] for t in buy_targets])}\n"
        return f"{gemini_guide}\n{summary}", all_results

    def analyze_batch_discovery(self, batch_data):
        """
        [V8.5.5] StrategyAdvisor용 일괄 분석 인터페이스
        batch_data: [{\"name\": \"삼성전자\", \"posts\": [...]}, ...]
        """
        return self.gemini.analyze_batch_discovery(batch_data)

    def analyze_initial_discovery(self, stock_name, posts):
        """
        [Legacy / Fallback] 1차 통과 종목 전용 최적화 분석 (개별 호출)
        """
        if not self.gemini.batch_model: return {"sentiment_score": 0, "summary": "AI 분석 불가", "keywords": []}
        
        # 대표글 본문/제목 결합 (용량 제한)
        text_content = "\n".join([f"[{p.get('title')}] {str(p.get('body', ''))[:200]}" for p in posts])
        
        prompt = f"""
        종목명: {stock_name}
        최근 토론방 게시글:
        {text_content}

        [V8.6.0 노이즈 배제 및 팩트 추출 규칙]
        - '가즈아', '상한가', '세력' 등 단순 선동 문구는 무시한다.
        - 게시글의 팩트(재료, 수급)에 집중하여 다음 형식의 JSON으로만 답변하세요:
        {{
            "sentiment_score": 점수(-10에서 10),
            "summary": "팩트 기반 한 줄 요약 (50자 이내)",
            "keywords": ["키워드1", "키워드2"]
        }}
        """
        try:
            response = self.gemini._call_gemini_safe(
                prompt, 
                model_type='batch',
                generation_config={"response_mime_type": "application/json"}
            )
            if response and response.text:
                return json.loads(response.text)
        except: pass
        return {"sentiment_score": 0, "summary": "분석 오류", "keywords": []}

    def generate_deep_dive_report(self, final_candidates):
        """
        [V8.5.3] 3차 통과 종목(최종 5선) 심층 리포트 생성
        - DART 공시 체크, 뉴스 교차 검증, 최종 매수 의견 포함
        """
        if not final_candidates: return "⚠️ 최종 분석 대상 종목이 없습니다."
        
        reports = []
        for stock in final_candidates:
            # [Step 1] 실시간 데이터 취득 (Engine 연동)
            dart_res = self.engine.fetch_dart_data(stock['code'])
            news_data = "최근 수급 유입 및 시장 관심도 증가" # TODO: 통합 뉴스 검색 엔진 연동 예정
            dart_data = dart_res.get('reason', '특이 공시 없음')
            
            # [V8.6.1 Brevity Policy]
            prompt = f"""
            시니어 퀀트 애널리스트로서 아래 종목에 대한 '초간결 딥다이브 리포트'를 작성하세요.
            
            종목: {stock['name']} ({stock['code']})
            AI 요약: {stock.get('posts_summary')}
            DART 공시/뉴스: {dart_data} / {news_data}
            
            [V8.6.2 극한 압축 규칙]
            긴 문장 절대 금지. 오직 아래 JSON 형식으로만 짧은 단어들로 답변하세요.
            {{
              "decision": "BUY|WATCH|REJECT",
              "reason": "단답형 한줄 액션 근거",
              "risk": "종토방/공시 리스크 (없으면 없음)",
              "highlights": ["키워드1", "키워드2"]
            }}
            """
            try:
                response = self.gemini._call_gemini_safe(prompt, model_type='report', generation_config={"response_mime_type": "application/json"})
                if response and response.text:
                    try:
                        data = json.loads(response.text)
                        if isinstance(data, list) and len(data) > 0:
                            data = data[0]
                        formatted = f"🔥 <b>{stock['name']}</b> [{data.get('decision', 'N/A')}]\n"
                        formatted += f"💡 <b>근거:</b> {data.get('reason', '')}\n"
                        formatted += f"⚠️ <b>리스크:</b> {data.get('risk', '없음')}\n"
                        formatted += f"✨ <b>핵심:</b> {', '.join(data.get('highlights', []))}\n"
                        reports.append(formatted)
                    except:
                        reports.append(response.text.strip())
            except:
                reports.append(f"⚠️ {stock['name']} 심층 분석 실패")

        header = f"🚀 **[Strategic Deep-Dive]** 최종 선정 {len(reports)}개 종목\n"
        header += f"📅 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        
        return header + "\n\n---\n\n".join(reports)
