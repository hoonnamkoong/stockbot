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
        self.batch_model_name = "gemini-2.5-flash-lite"
        self.report_model_name = "gemini-2.5-flash"
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
        GROUP_SIZE = 10
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

            [V8.6.2 분석 규칙 - 강화된 객관성]
            1. 감정적 단어(가즈아, 존버, 떡상 등) 및 선동 문구는 무조건 배제하고 0점 처리.
            2. 다음 핵심 키워드를 반드시 우대하여 분석에 포함: '분석', '추세', '전망', '공시', '뉴스', '따르면', '의하면'.
            3. summary는 내용이 풍부할 경우 2~3문장의 명사형 요약 가능. (예: 외인 매수세 유입에 따른 추세 전환 전망. 공시 기반 신규 수주 확인.)
            4. keywords는 3개 이내 핵심 전문 용어만 추출.

            [분석 대상 데이터]
            {json.dumps(cleaned_batch, ensure_ascii=False)}
            
            각 종목별로 다음 JSON 배열 형식으로만 응답하세요:
            [
                {{
                    "code": "005930",
                    "sentiment": 점수(-10 ~ 10),
                    "summary": "초간결 명사 요약",
                    "keywords": ["키워드1", "키워드2"]
                }}
            ]
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
                    
                    if isinstance(parsed, dict) and 'results' in parsed:
                        parsed = parsed['results']
                        
                    if isinstance(parsed, list):
                        for item in parsed:
                            if isinstance(item, dict):
                                if 'code' in item:
                                    all_results[item['code']] = item
                                else:
                                    for k, v in item.items():
                                        all_results[k] = v
                    elif isinstance(parsed, dict):
                        all_results.update(parsed)
            except Exception as e:
                print(f"[GeminiAgent] Group Batch 분석 오류: {e}")

        final_results = {}
        for s in batch_data:
            code = s.get('code')
            final_results[code] = all_results.get(code, {"sentiment": 0, "summary": "분석 오류", "keywords": []})
            
        return final_results

    def analyze_bulk_sentiment(self, bulk_data):
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
        return self.gemini.analyze_batch_discovery(batch_data)

    def analyze_initial_discovery(self, stock_name, posts):
        if not self.gemini.batch_model: return {"sentiment_score": 0, "summary": "AI 분석 불가", "keywords": []}
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
            response = self.gemini._call_gemini_safe(prompt, model_type='batch', generation_config={"response_mime_type": "application/json"})
            if response and response.text:
                return json.loads(response.text)
        except: pass
        return {"sentiment_score": 0, "summary": "분석 오류", "keywords": []}

    def select_sell_candidate(self, holdings: list) -> dict:
        """
        [V50.7] 보유 종목 중 매도가 필요한 1종목을 AI가 선정합니다.
        """
        if not holdings:
            return None
            
        def _parse_rate(val):
            if val is None: return 0.0
            try:
                return float(str(val).replace('%', '').replace(',', '').strip())
            except (ValueError, TypeError):
                return 0.0

        # 수익률 낮은 순으로 정렬 후 1종목 선정하여 AI 판단
        sorted_holdings = sorted(holdings, key=lambda x: _parse_rate(x.get('profit_rate', 0)))
        candidate = sorted_holdings[0]

        prompt = f"""
        당신은 전문 트레이더입니다. 아래 보유 종목을 분석하여 현재 시장 상황에서 '매도'가 적절한지 판단하세요.
        
        [보유 종목 데이터]
        {json.dumps(candidate, ensure_ascii=False)}
        
        [선정 기준]
        1. 수익률이 지나치게 높거나 낮은 종목 (익절/손절)
        2. 최근 주가 흐름이 둔화되거나 꺾인 종목
        
        오직 아래 JSON 형식으로만 답변하세요:
        {{
            "code": "종목코드",
            "name": "종목명",
            "reason": "매도 추천 사유 (한 문장)"
        }}
        """
        try:
            response = self.gemini._call_gemini_safe(prompt, model_type='batch', generation_config={"response_mime_type": "application/json"})
            if response and response.text:
                data = json.loads(response.text)
                target = next((h for h in holdings if h['code'] == data.get('code')), None)
                if target:
                    target['sell_reason'] = data.get('reason', '수익/손실 관리 필요')
                    return target
        except:
            pass
        return None

    def generate_deep_dive_report(self, final_candidates, sell_candidate=None):
        """
        [V8.5.4] 3차 통과 종목 심층 리포트 생성 (유저 요청 양식 반영)
        - 구성: 종목명/추천순위, 사업요약, 추천근거, 목표가, 리스크
        """
        if not final_candidates and not sell_candidate:
            return "⚠️ 분석 대상 종목이 없습니다."
        
        reports = []
        
        # 1. 스크래퍼 기반 추천 종목 (최대 2개)
        for stock in final_candidates[:2]:
            dart_res = self.engine.fetch_dart_data(stock['code'])
            dart_data = dart_res.get('reason', '특이 공시 없음')
            
            prompt = f"""
            시니어 애널리스트로서 아래 종목의 '상세 리포트'를 작성하세요.
            
            종목: {stock['name']} ({stock['code']})
            현재가: {stock.get('price', stock.get('current_price', 0))}원
            순위: {stock.get('rank', 'N/A')}위
            
            [분석 데이터]
            - 외인 변화: {stock.get('foreign_change', 0):+.2f}%p
            - 토론 요약: {stock.get('posts_summary')}
            - 공시: {dart_data}
            
            [리포트 작성 규칙]
            1. 'rank_and_recommendation': "[{stock.get('rank')}위] 매수 추천" 또는 "강력 매수" 등의 등급 제시.
            2. 'business_summary': 기업의 주요 사업 내용을 1~2문장으로 요약.
            3. 'rationale': 게시글 증가 이유, 뉴스, 수급, 섹터 동향을 종합 분석하여 3~5줄로 기술.
            4. 'target_price': 현재가 -> 목표가 형식으로 제시 (예: 50,000원 -> 65,000원).
            5. 'risk': 주의해야 할 리스크 요소 기술.
            
            오직 아래 JSON 형식으로만 답변하세요:
            {{
              "rank_and_recommendation": "순위 및 추천등급",
              "business_summary": "주요 사업 요약",
              "rationale": "종합 분석 추천 근거",
              "target_price_flow": "현재가 -> 목표가",
              "risk": "리스크 요인"
            }}
            """
            try:
                response = self.gemini._call_gemini_safe(prompt, model_type='report', generation_config={"response_mime_type": "application/json"})
                if response and response.text:
                    data = json.loads(response.text)
                    formatted = f"📌 <b>{stock['name']}</b> ({data.get('rank_and_recommendation')})\n"
                    formatted += f"🏢 <b>사업 요약:</b> {data.get('business_summary')}\n"
                    formatted += f"💡 <b>추천 근거:</b> {data.get('rationale')}\n"
                    formatted += f"🎯 <b>목표가:</b> {data.get('target_price_flow')}\n"
                    formatted += f"⚠️ <b>리스크:</b> {data.get('risk')}\n"
                    reports.append(formatted)
            except:
                reports.append(f"⚠️ {stock['name']} 상세 분석 실패")

        # 2. 실전 계좌 매도 추천 종목 (1개)
        if sell_candidate:
            prompt = f"""
            보유 종목 중 매도가 필요한 아래 종목의 '매도 리포트'를 작성하세요.
            
            종목: {sell_candidate['name']} ({sell_candidate['code']})
            현재가: {sell_candidate['current_price']}원
            수익률: {sell_candidate['profit_rate']}%
            매도 선정 사유: {sell_candidate.get('sell_reason')}
            
            위 정보를 바탕으로 아래 항목을 작성하세요:
            1. 'recommendation': "매도 추천" 또는 "비중 축소"
            2. 'business_summary': 주요 사업 요약
            3. 'rationale': 왜 지금 팔아야 하는지 기술적/심리적 근거 분석
            4. 'target_price_flow': 현재가 -> 손절/익절 목표가
            5. 'risk': 보유 시 발생할 수 있는 추가 하방 리스크
            
            JSON 형식:
            {{
              "recommendation": "매도/비중축소",
              "business_summary": "사업 요약",
              "rationale": "매도 근거",
              "target_price_flow": "현재가 -> 탈출가",
              "risk": "보유 리스크"
            }}
            """
            try:
                response = self.gemini._call_gemini_safe(prompt, model_type='report', generation_config={"response_mime_type": "application/json"})
                if response and response.text:
                    data = json.loads(response.text)
                    formatted = f"📉 <b>{sell_candidate['name']}</b> (실전계좌 {data.get('recommendation')})\n"
                    formatted += f"🏢 <b>사업 요약:</b> {data.get('business_summary')}\n"
                    formatted += f"💡 <b>매도 근거:</b> {data.get('rationale')}\n"
                    formatted += f"🎯 <b>목표가:</b> {data.get('target_price_flow')}\n"
                    formatted += f"⚠️ <b>리스크:</b> {data.get('risk')}\n"
                    reports.append(formatted)
            except:
                pass

        header = f"🚀 **[Strategic Deep-Dive]** 상세 리포트\n"
        header += f"📅 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        
        return header + "\n\n---\n\n".join(reports)
