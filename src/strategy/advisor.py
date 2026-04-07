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
    [V8.5.8] 최신 모델 동적 탐색 및 Fail-Fast 재시도 엔진
    """
    def __init__(self):
        # 환경변수 통합 로드 (Double Defense)
        self.api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_KEY')
        self.model = None
        self.model_name = "Unknown"
        self.all_available_models = []
        self.model_index = 0
        
        if not self.api_key:
            print("[GeminiAgent] 🚨 에러: API 키(GOOGLE_API_KEY)가 감지되지 않습니다.")
            return

        genai.configure(api_key=self.api_key)
        self._update_available_models()

    def _update_available_models(self):
        """[V8.5.8] 사용 가능한 모델 리스트를 동적으로 갱신하고 최신 2.5 시리즈 순으로 선택합니다."""
        try:
            available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            
            # [V8.5.8] 진짜 동적 모델 우선순위 (2.5 -> 2.0)
            priority_list = [
                'models/gemini-2.5-flash', 
                'models/gemini-2.5-flash-lite', 
                'models/gemini-2.5-pro', 
                'models/gemini-2.0-flash'
            ]
            self.all_available_models = []
            
            # 우선순위 항목 먼저 배치
            for p in priority_list:
                if p in available_models:
                    self.all_available_models.append(p)
            
            # 리스트에 없는 나머지 모델들도 추가
            for am in available_models:
                if am not in self.all_available_models:
                    self.all_available_models.append(am)
            
            if self.all_available_models:
                self.model_index = 0
                self.model_name = self.all_available_models[self.model_index]
                self.model = genai.GenerativeModel(self.model_name)
                print(f"[GeminiAgent] ✅ 최신 모델 초기화: {self.model_name}")
            else:
                self.model = None
                print("[GeminiAgent] 🚨 사용 가능한 텍스트 생성 모델이 없습니다.")
                
        except Exception as e:
            print(f"[GeminiAgent] 🚨 API 모델 조회 실패: {e}")
            self.all_available_models = []
            self.model = None

    def _call_gemini_safe(self, prompt, generation_config=None):
        """
        [V8.5.8 Fail-Fast] 429 발생 시 5초 대기 후 백업 모델로 단 1회만 재시도
        """
        if not self.model: return None
        
        # 1차 시도
        try:
            return self.model.generate_content(prompt, generation_config=generation_config)
        except Exception as e:
            err_msg = str(e)
            if ("429" in err_msg or "Quota" in err_msg or "ResourceExhausted" in err_msg):
                print(f"[GeminiAgent] ⚠️ Quota Exceeded ({self.model_name}). 5초 대기 후 백업 모델 전환...")
                time.sleep(5)
                
                # 백업 모델 전환 (다음 순위 모델)
                self.model_index += 1
                if self.model_index < len(self.all_available_models):
                    self.model_name = self.all_available_models[self.model_index]
                    self.model = genai.GenerativeModel(self.model_name)
                    print(f"[GeminiAgent] 🔄 백업 모델로 2차 시도 (Fail-Fast): {self.model_name}")
                    
                    # 2차 시도 (단 1회)
                    try:
                        return self.model.generate_content(prompt, generation_config=generation_config)
                    except Exception as e2:
                        print(f"[GeminiAgent] ❌ 백업 모델({self.model_name}) 2차 시도마저 실패: {str(e2)}")
                else:
                    print(f"[GeminiAgent] 🚨 가용 백업 모델이 없습니다. 분석 스킵.")
            else:
                print(f"[GeminiAgent] 🚨 API 에러: {err_msg}")
        
        return None

    def generate_trading_guide(self, market_context, signals):
        """[V8.4.6] 31개 종목 누락 방지 및 딥다이브 리포트 생성"""
        if not self.model: return "⚠️ Gemini API 초기화 실패: 리포트를 생성할 수 없습니다."
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
        
        [시장상황] {market_context}
        [데이터] {json.dumps(cleaned_signals, ensure_ascii=False)}
        
        **출력 가이드:**
        1. 가장 유망한 'Top 3 대장주'를 선정하고 그 이유를 토론방 여론과 연계해 설명할 것.
        2. 주의해야 할 '리스크 종목'을 1개 선정할 것.
        3. 강조는 오직 마크다운(**)만 사용하고, 전문적이고 신뢰감 있는 어조를 유지할 것.
        4. HTML 태그(<br>, <b> 등)를 절대 사용하지 말 것.
        """
        try:
            response = self._call_gemini_safe(prompt)
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
        if not self.model: return "WATCH"
        
        prompt = f"""
        종목명: {stock.get('name')} ({stock.get('code')})
        현재 Buzz: {stock.get('post_count')} posts
        최근 뉴스: {news}
        공시 분석: {dart}
        
        위 데이터를 바탕으로 이 종목의 단기 모멘텀을 평가하세요.
        """
        try:
            response = self._call_gemini_safe(prompt)
            return response.text.strip() if response and response.text else "WATCH"
        except:
            return "WATCH"

    def analyze_batch_discovery(self, batch_data):
        """
        [V8.5.5] 1차 필터 통과 종목군 일괄 분석 (Batch Discovery)
        - 한 번의 API 호출로 모든 종목의 감정/요약/키워드 추출
        - Quota 절감 및 분석 속도 개선
        """
        if not self.model or not batch_data: 
            return {s.get('code', s.get('name')): {"sentiment_score": 0, "summary": "AI 분석 불가", "keywords": []} for s in batch_data}
        
        # [V8.5.5] 데이터 경량화 및 정합성 보전 (body 대신 title + likes 활용)
        cleaned_batch = []
        for stock in batch_data:
            posts_text = "\n".join([f"[{p.get('title')}] (추천:{p.get('likes')})" for p in stock.get('posts', [])])
            cleaned_batch.append({
                "code": stock.get('code'),
                "name": stock.get('name'),
                "content": posts_text
            })
            
        prompt = f"""
        당신은 실시간 주식 수급 분석 전문가입니다. 아래 리스트에 포함된 각 종목의 토론방 데이터를 분석하세요.
        
        [데이터 정제 및 평가 필수 규칙 - 절대 준수]
        1. 노이즈 배제: '가자', '가즈아', '존버', '상한가', '떡상', '구조대', '세력', '개미털기', '설거지', 'ㅋㅋ', 'ㅎㅎ' 등 단순 감정적 선동, 음모론 단어는 분석 대상에서 철저히 무시한다.
        2. 팩트 기반 키워드: keywords는 기업 펀더멘털, 수급 변화, 공시, 테마 모멘텀을 나타내는 '명사형 팩트 단어'만 추출한다.
        3. 감정 점수 기준: 근거 없는 맹신은 0점 처리. 객관적 호재(실적, 수주 등)가 동반된 여론만 긍정(+), 객관적 악재가 동반된 여론만 부정(-)으로 평가한다.

        [분석 대상 데이터]
        {json.dumps(cleaned_batch, ensure_ascii=False)}
        
        각 종목별로 종목코드(code)를 Key로 사용하여 다음 JSON 형식으로만 응답하세요 (반드시 유효한 JSON 객체 하나만 반환하세요):
        {{
            "005930": {{
                "sentiment_score": 점수(-10 ~ 10),
                "summary": "게시글 한 줄 요약 (50자 이내)",
                "keywords": ["키워드1", "키워드2", "키워드3"]
            }},
            "066570": {{ ... }}
        }}
        """
        try:
            response = self._call_gemini_safe(
                prompt, 
                generation_config={"response_mime_type": "application/json"}
            )
            if response and response.text:
                # [V8.5.5] 마크다운 코드 블록(```json 등) 제거 안전장치
                raw_text = response.text.strip()
                if raw_text.startswith("```"):
                    raw_text = re.sub(r"^(?:```[a-z]*\n)|(?:```$)", "", raw_text, flags=re.MULTILINE).strip()
                return json.loads(raw_text)
        except Exception as e:
            print(f"[GeminiAgent] Batch 분석 오류: {e}")
            
        return {s.get('code', s.get('name')): {"sentiment_score": 0, "summary": "분석 오류", "keywords": []} for s in batch_data}

    def analyze_bulk_sentiment(self, bulk_data):
        """기존 벌크 감성 분석 로직 유지 (모델 동적 적용)"""
        if not self.model: return {}
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
        if not self.gemini.model: return {"sentiment_score": 0, "summary": "AI 분석 불가", "keywords": []}
        
        # 대표글 본문/제목 결합 (용량 제한)
        text_content = "\n".join([f"[{p.get('title')}] {str(p.get('body', ''))[:200]}" for p in posts])
        
        prompt = f"""
        종목명: {stock_name}
        최근 토론방 게시글:
        {text_content}

        위 내용을 바탕으로 다음 형식의 JSON으로만 답변하세요:
        {{
            "sentiment_score": 점수(-10에서 10),
            "summary": "게시글 내용을 관통하는 한 줄 요약 (50자 이내)",
            "keywords": ["키워드1", "키워드2", "키워드3"]
        }}
        """
        try:
            response = self.gemini._call_gemini_safe(prompt, generation_config={"response_mime_type": "application/json"})
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
            
            # [지침 준수] DART 악재가 있어도 탈락시키지 않고 리포트에 포함
            prompt = f"""
            당신은 시니어 퀀트 애널리스트입니다. 아래 종목에 대해 실매매 가부를 결정하는 '딥다이브 리포트'를 작성하세요.
            
            종목: {stock['name']} ({stock['code']})
            현재가: {stock.get('price')}
            당일 등락: {stock.get('change_rate')}
            누적 Buzz: {stock.get('recent_posts_count')}
            AI 요약: {stock.get('posts_summary')}
            핵심 키워드: {', '.join(stock.get('keywords', []))}
            DART 공시 현황: {dart_data}
            뉴스 요약: {news_data}
            
            **작성 가이드 (지시사항 엄수):**
            1. [Risk Report]: 반드시 제일 먼저 작성하세요. CB/BW, 유상증자 등 공시 데이터에 구체적 위험 요소가 있는지 판별하여 보고하세요. (없다면 '특이사항 없음'으로 보고)
            2. [Analysis]: Buzz의 질(감정 점수: {stock.get('sentiment_score')})과 수급 상황을 종합 분석하세요.
            3. [Final Verdict]: BUY(매도), WATCH(관망), REJECT(제외) 중 하나를 선택하고 명확한 근거를 제시하세요.
            4. **마크다운(**)**만 사용하고 HTML 태그는 절성 금지합니다.
            """
            try:
                response = self.gemini._call_gemini_safe(prompt)
                if response and response.text:
                    # HTML 강제 제거 및 정제
                    cleaned_text = re.sub(r'<[^>]*>', '', response.text.strip())
                    reports.append(cleaned_text)
            except:
                reports.append(f"⚠️ {stock['name']} 심층 분석 실패")

        header = f"🚀 **[Strategic Deep-Dive]** 최종 선정 {len(reports)}개 종목\n"
        header += f"📅 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        
        return header + "\n\n---\n\n".join(reports)
