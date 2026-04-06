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

# [Rule 4.3] 투자 전략 조언 및 AI 분석을 담당하는 핵심 모듈입니다.
# 실전/가상 포트폴리오 데이터를 통합하고, Gemini AI를 사용하여 매매 가이드를 생성합니다.

# --- Trade Module Imports ---
# [Rule 4.3] 통합된 src/trade 패키지로부터 인증 및 잔고 모듈을 표준 경로로 가져옵니다.
from src.trade.auth import get_access_token, load_env
from src.trade.balance import get_balance

# from .engine import StrategyEngine (순환 참조 방지를 위해 지연 로딩으로 이동)

# --- 1. Gemini Agent Logic (AI 분석 엔진) ---
class GeminiAgent:
    """
    [What] Google Gemini 모델을 사용하여 종목의 모멘텀을 분석하고 텍스트 리포트를 생성합니다.
    [Why] 기술적 지표만으로는 파악하기 힘든 뉴스의 무게감과 시장 분위기를 AI가 최종 검증하기 위함입니다.
    """
    def __init__(self):
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        self.api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_KEY')
        self.model = None
        self.model_name = "Unknown"
        
        if self.api_key:
            genai.configure(api_key=self.api_key)
            try:
                # 1. API 키로 접근 가능한 모든 텍스트 생성 모델 리스트 동적 조회
                available_models = [
                    m.name for m in genai.list_models() 
                    if 'generateContent' in m.supported_generation_methods
                ]
                
                # 2. 선호하는 고성능 모델 순서대로 매칭 (무료 티어 한도 및 성능 고려)
                # [V8.2] gemini-2.5-flash 최우선 모델 전격 배치
                preferred_keywords = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro-002']
                selected_model_name = None
                
                for keyword in preferred_keywords:
                    for am in available_models:
                        if keyword in am:
                            selected_model_name = am
                            break
                    if selected_model_name:
                        break
                        
                # 3. 선호 모델이 없으면 구글이 내려준 리스트의 첫 번째 모델 사용 (404 완벽 차단)
                if not selected_model_name and available_models:
                    selected_model_name = available_models[0]
                    
                if selected_model_name:
                    # 'models/' 접두사가 이미 포함되어 있으므로 안전하게 바로 객체 생성
                    self.model = genai.GenerativeModel(selected_model_name)
                    self.model_name = selected_model_name
                    print(f"[GeminiAgent] ✅ 동적 모델 로드 성공: {selected_model_name}")
                else:
                    print("[GeminiAgent] 🚨 사용 가능한 텍스트 생성 모델이 없습니다.")
                    
            except Exception as e:
                print(f"[GeminiAgent] 🚨 API 모델 조회 실패: {e}")
        else:
            print("[GeminiAgent] 🚨 API 키가 누락되었습니다.")

    def evaluate_momentum(self, stock_info, news_list, dart_info):
        """
        [지시사항 3] Gemini V2 내러티브 및 JSON 포맷 강제
        """
        if not self.model:
            return {"decision": "REJECTED", "momentum_score": 0, "telegram_narrative": "API 키 오류"}
            
        prompt = f"""
        당신은 공격적인 퀀트 트레이더입니다. 아래 데이터를 바탕으로 이 종목이 '4월 어텐션 모멘텀'의 최종 승인 대상인지 판별하세요.
        
        데이터:
        - 대상 종목: {json.dumps(stock_info, ensure_ascii=False)}
        - 관련 뉴스: {json.dumps(news_list, ensure_ascii=False)}
        - 공시 정보: {json.dumps(dart_info, ensure_ascii=False)}
        
        요구사항:
        - 단순 데이터 나열이 아닌, 매수 근거에 대한 전문적인 스토리텔링 코멘트를 작성하세요.
        - 'telegram_narrative'는 텔레그램으로 전송될 최종 리포트의 핵심입니다.
        - 반드시 다음 JSON 형식을 엄수하세요:
        {{
            "decision": "APPROVED" | "REJECTED",
            "telegram_narrative": "전문적인 스토리텔링 코멘트..."
        }}
        """
        try:
            # [FIX] 지시사항: response_mime_type="application/json" 강제
            response = self.model.generate_content(
                prompt, 
                generation_config={"response_mime_type": "application/json"}
            )
            res_json = json.loads(response.text)
            
            # [FIX] 지시사항: decision이 APPROVED일 때만 최종 매수 타겟 확정 로직을 위해 
            # 형식을 보장합니다.
            if "decision" not in res_json: res_json["decision"] = "REJECTED"
            return res_json
        except Exception as e:
            # [FIX] 지시사항: Silent Failure 방지 및 상세 로깅
            print(f"[GeminiAgent] V2 JSON 분석 치명적 오류: {str(e)}")
            import traceback
            traceback.print_exc()
            return {"decision": "REJECTED", "telegram_narrative": f"분석 오류 발생: {str(e)[:100]}"}

    def generate_trading_guide(self, market_context, sentinel_signals):
        """[What] 텔레그램 리포트를 인사이트 중심의 딥다이브 체제로 개편합니다."""
        if not self.model: return "⚠️ Gemini API 초기화 실패: 리포트를 생성할 수 없습니다."
        
        # [V9.5] 데이터 무결성 검사
        if not sentinel_signals:
            return "⚠️ 제공된 분석 데이터가 없습니다 (시그널 부재)."

        # 상위 5개와 나머지 10개 분리
        top_5 = sentinel_signals[:5]
        others = sentinel_signals[5:15]

        # [V9.5 핵심 수정] 데이터 인젝션 강화
        prompt = f"""
        당신은 공격적인 퀀트 분석가이며 '인사이트 중심 딥다이브' 리포트의 수석 에디터입니다. 
        아래 제공된 [실제 데이터]만을 사용하여 리포트를 작성하세요. 
        데이터가 '[]'나 '비어있음'으로 표시되지 않도록 각 종목의 세부 필드를 전수 분석하여 반영하세요.

        [실제 데이터 (Raw Data)]
        - 시장 상황: {market_context}
        - 상위 5개 타겟 상세: {json.dumps(top_5, ensure_ascii=False)}
        - 나머지 10개 요약: {json.dumps(others, ensure_ascii=False)}
        
        요구사항 (PM 보고용 요약 리포트 스타일):
        1. 시황 브리핑 (Market Brief): 상위 5개 종목 기반 주도 섹터/테마 위주 3줄 이내 요약.
        2. Top 5 Deep-Dive: 상위 5개 종목 각각에 대해 아래 4개 요소를 구체적 데이터 기반으로 서술.
           - 버즈 발생 원인 (Trigger): 뉴스/공시 텍스트를 인용하여 한 문장 정의.
           - 커뮤니티 심층 분석 (Community Insight): 본문(bodies)의 핵심 논점 요약.
           - 공시/뉴스 팩트 체크: 버즈와 일치하는 실재하는 텍스트 인용.
           - AI 최종 판단: [ML 확률 + 감성 점수]를 수치로 표기하고 '진짜 호재' 여부 판정.
        3. 나머지 10개 종목: [종목명 | AI 점수 | 핵심 키워드] 위주로 리스트화.
        
        🚨 절대 금기 사항:
        - "[상위 종목 1]" 또는 "[뉴스/공시]" 같은 템플릿 대괄호([]) 형식을 그대로 출력하지 말 것.
        - "제공된 데이터가 부족합니다" 같은 안내 문구를 출력하지 말 것. 데이터가 부족하면 현재 있는 수치(AI 점수 등)로만 판단할 것.
        - 오직 전문가용 불렛포인트(*)와 핵심 키워드 중심의 실전 리포트만 출력할 것.
        """
        try:
            response = self.model.generate_content(prompt)
            if response and response.text:
                return response.text
            return "⚠️ AI 모델 응답이 비어있습니다. (데이터 부족)"
        except Exception as e:
            return f"⚠️ 전략 리포트 생성 실패: {str(e)}"

    def analyze_bulk_sentiment(self, bulk_data: list) -> dict:
        """
        [V8.2] 2단계 (Bulk Body Sentiment) 분석을 수행합니다.
        여러 종목의 베스트 게시글 본문을 한 번에 분석하여 감성 점수(-10 ~ 10)를 산출합니다.
        """
        if not self.model: return {}
        
        # [V9.3 강화] 토큰 제한 방지를 위한 본문 슬라이싱 (종목당 최대 300자)
        processed_bulk = []
        for s in bulk_data:
            processed_bulk.append({
                "code": s.get('code'),
                "name": s.get('name'),
                "bodies": [str(b)[:300] for b in s.get('bodies', [])]
            })

        prompt = f"""
        당신은 주식 시장의 대중 심리를 분석하는 고도의 인공지능 분석가입니다. 
        다음 종목 리스트와 각 종목별 추천 상위 5개 게시글 본문을 읽고, 
        대중의 열광도와 호재의 논리성을 바탕으로 'AI 감성 점수(-10에서 10 사이)'를 부여하세요.
        
        - 10: 폭발적인 호재와 압도적인 대중 열광
        - 0: 중립 또는 단순 정보 공유
        - -10: 극심한 공포와 악재의 구체화
        
        분석 데이터:
        {json.dumps(processed_bulk, ensure_ascii=False)}
        
        출력 형식 (반드시 아래 JSON 형식만 답변하세요. 다른 설명은 금지합니다):
        {{
            "종목코드": 점수(숫자),
            "종목코드": 점수(숫자)
        }}
        """
        try:
            # generation_config 적용하여 JSON 응답 유도
            response = self.model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            
            # [Debugging] AI 원본 응답 로그 출력
            raw_text = response.text.strip()
            # print(f"[Gemini] Raw Sentiment Response: {raw_text[:500]}...")

            # 마크다운 백틱 제거 정규식 강화
            clean_json = re.sub(r'```(?:json)?\n?|```', '', raw_text).strip()
            
            # JSON 추출 (중괄호 사이 내용만)
            match = re.search(r'\{.*\}', clean_json, re.DOTALL)
            if match:
                return json.loads(match.group(0))
                
            return json.loads(clean_json) # 정규식 실패 시 전체 파싱 시도
            
        except Exception as e:
            print(f"[StrategyAdvisor] Bulk Sentiment AI 호출/파싱 실패: {e}")
            if 'response' in locals():
                print(f"[Raw Output]: {response.text[:200]}")
            return {}
        except Exception as e:
            import traceback
            # [FIX] 지시사항: 에러 원인 명확히 로깅
            print(f"[GeminiAgent] AI 가이드 생성 치명적 오류: {str(e)}")
            traceback.print_exc()
            return f"⚠️ **AI 가이드 생성 중 오류 발생**: {str(e)[:150]}\n\n(시스템 로그를 확인해 주세요)"

# --- 2. Strategy Advisor (전략 실행 코디네이터) ---
class StrategyAdvisor:
    """
    [What] 포트폴리오 조회, 종목 분석, 리포트 생성을 총괄하는 클래스입니다.
    [Why] 여러 분석 엔진(Engine, Gemini)과 데이터 소스(KIS, Local)를 하나로 묶어 scraper.py에서 쉽게 사용할 수 있게 합니다.
    """
    def __init__(self):
        from .virtual_portfolio import VirtualPortfolioManager
        from .engine import StrategyEngine
        self.vpm = VirtualPortfolioManager() # 가상 계좌 관리자
        self.engine = StrategyEngine() # 기술적 분석 엔진
        self.gemini = GeminiAgent() # AI 분석 에이전트

    def analyze_bulk_sentiment(self, bulk_data: list) -> dict:
        """
        [V8.2] 2단계 (Bulk Body Sentiment) 분석을 실행합니다.
        advisor.py 내의 GeminiAgent를 통해 대량의 종목 감성 점수를 한 번에 산출합니다.
        데이터 누락 시 모든 종목에 대해 0점을 반환합니다.
        """
        try:
            if not bulk_data:
                return {}
            
            # GeminiAgent의 실제 분석 함수 호출
            result = self.gemini.analyze_bulk_sentiment(bulk_data)
            
            # 입력된 모든 티커에 대해 결과 보장 (누락 시 0점)
            final_map = {}
            for item in bulk_data:
                ticker = item.get('code')
                if ticker:
                    final_map[ticker] = result.get(ticker, 0)
            
            return final_map
            
        except Exception as e:
            print(f"[StrategyAdvisor] Error in bulk sentiment: {e}")
            # 전체 실패 시 안전하게 0점 반환 로직
            return {item.get('code'): 0 for item in bulk_data if item.get('code')}

    def fetch_portfolio(self):
        """
        [What] 실전(KIS) 또는 가상 계좌의 보유 종목 정보를 가져옵니다.
        [Rule 4.4] 실전 계좌 조회 실패 시에도 전체 프로세스가 중단되지 않도록 예외 처리를 강화했습니다.
        """
        is_virtual = os.environ.get("KIS_IS_VIRTUAL", "false").lower() == "true"
        holdings = {}

        if not is_virtual:
            print("[Advisor] 실전 KIS 계좌 정보 조회 중...")
            try:
                # [Safety] 임포트 에러나 호출 실패 시 텔레그램 알림을 위해 내부에서 예외 처리
                from trade.balance import get_balance
                res = get_balance()
                
                if res and isinstance(res, dict) and "error" not in res:
                    for h in res.get('holdings', []):
                        holdings[h['code']] = {
                            'name': h['name'],
                            'qty': h['qty'],
                            'avg_price': h['avg_price'],
                            'current_price': h['current_price'],
                            'profit_rate': h['profit_rate']
                        }
                    print(f"[Advisor] 실전 포트폴리오 로드 완료: {len(holdings)}개 종목")
                    return holdings
                else:
                    err = res.get('error') if res else 'Unknown error'
                    print(f"[Advisor] ⚠️ 실전 조회 건너뜀 (가상계좌 활용): {err}")
            except Exception as e:
                # [Critical] 어떠한 상황에서도 리포트 생성이 중단되지 않도록 모든 예외를 잡음
                print(f"[Advisor] ❌ 실전 계좌 조회 중 치명적 오류 (건너뜀): {e}")

        # 실전 계좌 실패 시 또는 모의 환경인 경우 가상 포트폴리오 로드
        print("[Advisor] 가상 포트폴리오 로드 중...")
        try:
            port_data = self.vpm.get_portfolio()
            for code, info in port_data.items():
                qty = info.get('quantity', 0)
                if qty > 0:
                    avg_price = info.get('average_buy_price', 0.0)
                    
                    # 네이버 금융을 통해 현재가를 동적으로 가져와 수익률 계산
                    current_price = avg_price
                    try:
                        res = requests.get(f"https://finance.naver.com/item/main.naver?code={code}", timeout=3)
                        soup = BeautifulSoup(res.text, 'html.parser')
                        price_tag = soup.select_one(".no_today .blind")
                        if price_tag:
                            current_price = float(price_tag.text.replace(',', ''))
                    except Exception as naver_e:
                        print(f"[Advisor] 현재가 갱신 실패 ({code}): {naver_e}")

                    profit_rate = ((current_price - avg_price) / avg_price) * 100.0 if avg_price > 0 else 0.0
                    
                    holdings[code] = {
                        'name': info.get('name', 'Unknown'),
                        'qty': qty,
                        'avg_price': avg_price,
                        'current_price': current_price,
                        'profit_rate': profit_rate
                    }
        except Exception as e:
            print(f"[Advisor] 가상 포트폴리오 조회 오류: {e}")
            
        print(f"[Advisor] 포트폴리오 로딩 최종 완료: {len(holdings)}개 항목")
        return holdings

    def fetch_specific_news(self, stock_code, stock_name):
        """특정 종목의 최신 뉴스 헤드라인을 수집합니다."""
        news_list = []
        try:
            encoded_name = urllib.parse.quote(stock_name)
            url = f"https://search.naver.com/search.naver?where=news&query={encoded_name}"
            res = requests.get(url, timeout=3)
            soup = BeautifulSoup(res.text, 'html.parser')
            titles = soup.select('.news_tit')
            for t in titles[:5]:
                news_list.append(t.get_text(strip=True))
        except Exception as e:
            print(f"[Advisor] 뉴스 수집 오류 ({stock_name}): {e}")
        return news_list

    def check_dart_filings(self, stock_name, stock_code):
        """
        [지시사항 2] 2차 검증 오버레이 (DART 크로스체크)
        """
        result = {"reject": False, "reason": "이상 없음"}
        
        # [ 지시사항 ] 기피 키워드(악재) 정의
        reject_kws = ["전환사채", "신주인수권부사채", "유상증자"]

        try:
            # 실시간 공시 페이지 파싱
            naver_url = f"https://finance.naver.com/item/news_notice.naver?code={stock_code}"
            n_res = requests.get(naver_url, timeout=5)
            soup = BeautifulSoup(n_res.text, 'html.parser')
            titles = soup.select('.title a')
            
            # 오늘 날짜 공시만 필터링 (V2 엄격성)
            today_str = datetime.datetime.now().strftime('%Y.%m.%d')
            
            for row in soup.select('tr'):
                date_td = row.select_one('.date')
                title_a = row.select_one('.title a')
                
                if date_td and title_a:
                    date = date_td.get_text(strip=True)
                    text = title_a.get_text(strip=True)
                    
                    if today_str in date: # 오늘 자 공시인 경우
                        if any(k in text for k in reject_kws):
                            result["reject"] = True
                            result["reason"] = f"DART 악재 발견: {text}"
                            print(f"[Advisor] 🚨 {stock_name} 2차 검증 탈락 (악재 공시: {text})")
                            break
                    
        except Exception as e:
            print(f"[Advisor] DART 분석 오류 ({stock_name}): {e}")
            
        return result

    def crosscheck_news_keywords(self, news_list, stock_name):
        """뉴스 리스트 존재 여부를 확인합니다."""
        return len(news_list) > 0

    def analyze_candidates(self, candidates, allow_buy=True):
        """
        [V2] 통합 분석 실행 및 결과 반환
        낡은 is_v2_target_passed 호출을 제거하고 엔진에 처리를 위임함.
        """
        print(f"[Advisor] 4월 V2 알고리즘 가동 - {len(candidates)} 종목 정밀 검정 시작")
        return self.engine.execute_simulation(candidates, allow_buy)

    def generate_report(self, candidates, allow_buy=True):
        """[What] 텔레그램으로 보낼 최종 가독성 있는 리포트 문자열을 생성합니다."""
        all_results = self.analyze_candidates(candidates, allow_buy=allow_buy)
        
        # 인사이트 중심 딥다이브 리포트 생성 (가장 상단에 배치)
        market_context = f"{len(candidates)}개 종목 분석 완료. 주도 섹터 및 모멘텀 분석 중심."
        gemini_guide = self.gemini.generate_trading_guide(market_context, all_results)
        
        # 하단 요약 섹션 (간결하게)
        summary = f"\n---\n📊 **시스템 요약 리포트 (V9.4)**\n"
        summary += f"📅 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        
        buy_targets = [r for r in all_results if r['signal'] == 'BUY']
        if buy_targets:
            summary += f"🔥 매수 승인: {', '.join([t['name'] for t in buy_targets])}\n"
        
        return f"{gemini_guide}\n{summary}", all_results
