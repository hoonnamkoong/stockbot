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
                # [FIX] gemini-2.5-flash를 최우선 모델로 고정
                preferred_keywords = ['gemini-2.5-flash', 'gemini-1.5-flash', 'gemini-2.0-flash', 'gemini-2.5-pro']
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
        """[What] 전체 시장Context와 신호를 바탕으로 하는 서술형 가이드를 생성합니다."""
        if not self.model: return "⚠️ Gemini API 초기화 실패: 리포트를 생성할 수 없습니다."
        
        prompt = f"""
        당신은 실전 주식 투자 전문가이며, '4월 V2 어텐션 모멘텀' 전략의 수석 분석가입니다. 
        제공된 15개 정예 종목 리스트를 바탕으로 통합 'Strategic Guide'를 작성하세요.
        
        데이터:
        - 시장 상황: {market_context}
        - 정예 종목 리스트 (상위 15개): {json.dumps(sentinel_signals, ensure_ascii=False)}
        
        요구사항:
        1. 첫 문장은 시장의 '분위기(Regime)'를 한 문장으로 정의하며 시작하세요.
        2. 15개 종목 전체의 흐름을 관통하는 핵심 테마와 특징을 분석하세요.
        3. 왜 특정 종목들을 주목해야 하는지, 그리고 리스크 요인은 무엇인지 논리적으로 설명하세요.
        4. '입니다/합니다'체를 사용하며 투자자에게 실질적인 도움이 되는 조언을 포함하세요.
        5. 수치 데이터를 근거로 제시하며, 전반적인 매매 전략(분할 매수 등)을 제안하세요.
        """
        try:
            response = self.model.generate_content(prompt)
            if response and response.text:
                return response.text
            return "⚠️ AI 모델 응답이 비어있습니다. (데이터 부족)"
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
        
        # 성적이 좋은 상위 종목 + 대응 종목 위주로 리포트 구성
        report = f"📊 **4월 V2 어텐션 모멘텀 리포트**\n"
        report += f"📅 일시: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        
        buy_targets = [r for r in all_results if r['signal'] == 'BUY']
        sell_targets = [r for r in all_results if 'SELL' in r['signal']]
        
        if buy_targets:
            report += "🔥 **[매수 승인 종목]**\n"
            for t in buy_targets:
                report += f"✅ **{t['name']}** ({t['code']})\n"
                report += f"💬 AI 분석: {t['reason']}\n\n"
        
        if sell_targets:
            report += "🚨 **[매도/대응 종목]**\n"
            for t in sell_targets:
                report += f"📉 **{t['name']}**: {t['signal']} ({t['reason']})\n"
            report += "\n"
            
        if not buy_targets and not sell_targets:
            report += "💤 특이 신호 종목 없음 (관망 유지)\n"
            
        market_context = f"{len(candidates)}개 종목 분석 완료. 포지션 사이징 규칙 적용됨."
        gemini_guide = self.gemini.generate_trading_guide(market_context, all_results)
        
        return f"{gemini_guide}\n\n{report}", all_results
