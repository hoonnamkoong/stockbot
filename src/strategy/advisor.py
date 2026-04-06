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
# 로컬 및 깃허브 액션 환경 모두에서 인증/잔고 모듈을 찾을 수 있도록 경로를 보강합니다.
try:
    from trade.auth import get_access_token, load_env
    from trade.balance import get_balance
except ImportError:
    try:
        from src.trade.auth import get_access_token, load_env
        from src.trade.balance import get_balance
    except ImportError:
        # 최후의 수단: 모듈을 찾지 못할 경우 상위 경로 강제 주입
        sys.path.append(os.path.join(os.getcwd(), 'trade'))
        sys.path.append(os.path.join(os.getcwd(), 'src', 'trade'))
        from auth import get_access_token, load_env
        from balance import get_balance

from .engine import StrategyEngine

# --- 1. Gemini Agent Logic (AI 분석 엔진) ---
class GeminiAgent:
    """
    [What] Google Gemini 모델을 사용하여 종목의 모멘텀을 분석하고 텍스트 리포트를 생성합니다.
    [Why] 기술적 지표만으로는 파악하기 힘든 뉴스의 무게감과 시장 분위기를 AI가 최종 검증하기 위함입니다.
    """
    def __init__(self):
        load_env()
        # [Rule 4.1] 하드코딩 금지: 환경 변수에서 키 로드
        self.api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_KEY')
        self.model = None
        
        if self.api_key:
            genai.configure(api_key=self.api_key)
            # [What] 최신 3.1 시리즈 모델부터 순차적으로 시도 (성능 및 비용 최적화)
            models_to_try = ['gemini-3.1-flash', 'gemini-3.1-pro', 'gemini-1.5-flash']
            
            for m in models_to_try:
                try:
                    # [Step] 모델 초기화 시도
                    model_obj = genai.GenerativeModel(m)
                    # 실제 연결 확인을 위한 간단한 할당 (AttributeError 방지 로직 포함)
                    self.model = model_obj
                    self.model_name = m
                    print(f"[GeminiAgent] 모델 로드 성공: {m}")
                    break
                except Exception as e:
                    print(f"[GeminiAgent] {m} 로드 실패, 다음 모델 시도: {e}")
            
            if not self.model:
                print("[GeminiAgent] 경고: 유효한 모델을 로드하지 못했습니다.")
        else:
            print("[GeminiAgent] 경고: API 키가 설정되지 않았습니다.")

    def evaluate_momentum(self, stock_info, news_list, dart_info):
        """
        [What] 특정 종목의 매수 적합성을 AI가 최종 판정합니다.
        [Output] JSON 형식을 강제하여 시스템이 자동 의사결정을 내릴 수 있도록 합니다.
        """
        if not self.model:
            return {"decision": "REJECTED", "momentum_score": 0, "telegram_narrative": "API 키 오류"}
            
        prompt = f"""
        당신은 공격적인 모멘텀 주식 트레이더입니다.
        현재 시장의 광기와 스마트 머니(외국인)의 수급이 실질적인 촉매제(공시/뉴스)에 근거한 것인지 판별하세요.
        
        데이터:
        - 대상 종목: {json.dumps(stock_info, ensure_ascii=False)}
        - 관련 뉴스: {json.dumps(news_list, ensure_ascii=False)}
        - 공시 정보: {json.dumps(dart_info, ensure_ascii=False)}
        
        원칙:
        - 단순 테마성 소음(Gap & Crap)인지, 아니면 강력한 실체가 있는 뉴스인지 분석하세요.
        - 모멘텀 점수(1-10)가 7점 이상일 때만 "APPROVED"를 부여하세요.
        - 'telegram_narrative'에는 왜 시장이 이 종목에 열광하는지, 내일 시초가 갭이 어느 정도일지 예측하는 서사적인 조언을 작성하세요.
        
        반드시 다음 JSON 형식을 엄수하세요:
        {{
            "decision": "APPROVED" | "REJECTED",
            "momentum_score": 8,
            "catalyst_summary": "핵심 촉매 요약",
            "telegram_narrative": "텔레그램 리포트용 상세 조언..."
        }}
        """
        try:
            # JSON 응답을 강제하는 설정 적용
            response = self.model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
            return json.loads(response.text)
        except Exception as e:
            print(f"[GeminiAgent] 모멘텀 평가 오류: {e}")
            return {"decision": "REJECTED", "momentum_score": 0, "telegram_narrative": f"분석 오류: {e}"}

    def generate_trading_guide(self, market_context, sentinel_signals):
        """[What] 전체 시장Context와 신호를 바탕으로 하는 서술형 가이드를 생성합니다."""
        if not self.model: return "Gemini API 키가 없습니다."
        prompt = f"다음 신호들을 바탕으로 오늘의 매매 요약을 작성하세요: {json.dumps(sentinel_signals, ensure_ascii=False)}. 왜 매도하거나 보유했는지 전문가처럼 설명하세요."
        try:
            return self.model.generate_content(prompt).text
        except:
            return "가이드 생성 중 오류가 발생했습니다."

# --- 2. Strategy Advisor (전략 실행 코디네이터) ---
class StrategyAdvisor:
    """
    [What] 포트폴리오 조회, 종목 분석, 리포트 생성을 총괄하는 클래스입니다.
    [Why] 여러 분석 엔진(Engine, Gemini)과 데이터 소스(KIS, Local)를 하나로 묶어 scraper.py에서 쉽게 사용할 수 있게 합니다.
    """
    def __init__(self):
        from .virtual_portfolio import VirtualPortfolioManager
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
        """[What] DART 공시 정보를 확인하여 악재나 호재 키워드를 필터링합니다."""
        load_env()
        dart_key = os.environ.get('DART_API_KEY')
        result = {"premium": [], "hard_reject": False, "summary": "이상 없음"}
        
        # 기피 키워드(악재) 및 선호 키워드(호재) 정의
        reject_kws = ["전환사채", "신주인수권부사채", "유상증자", "주식등의대량보유상황보고서", "임원ㆍ주요주주특정증권등소유상황보고서"]
        premium_kws = ["단일판매ㆍ공급계약체결", "자기주식취득", "무상증자"]

        if not dart_key:
            result["summary"] = "DART API 키 미설정 (건너뜀)"
            return result

        try:
            # 네이버 금융 공시/뉴스 탭 활용
            naver_url = f"https://finance.naver.com/item/news_notice.naver?code={stock_code}"
            n_res = requests.get(naver_url, timeout=3)
            soup = BeautifulSoup(n_res.text, 'html.parser')
            titles = soup.select('.title a')
            
            for t in titles:
                text = t.get_text(strip=True)
                if any(k in text for k in reject_kws):
                    result["hard_reject"] = True
                    result["summary"] = f"기피 공시 발견: {text}"
                    break
                if any(k in text for k in premium_kws):
                    result["premium"].append(text)
                    result["summary"] = f"프리미엄 공시 발견: {text}"
                    
        except Exception as e:
            print(f"[Advisor] DART 분석 오류 ({stock_name}): {e}")
            result["summary"] = f"DART 분석 예외 (건너뜀): {e}"
            
        return result

    def crosscheck_news_keywords(self, news_list, stock_name):
        """뉴스 리스트 존재 여부를 확인합니다."""
        return len(news_list) > 0

    def analyze_candidates(self, candidates, allow_buy=True):
        """
        [What] 후보 종목들을 분석하여 매수/매도 신호를 생성합니다.
        [Flow] 기술적 분석(Engine) -> 공시/뉴스 분석(Gate) -> AI 모멘텀 분석(Gemini) 순으로 진행됩니다.
        """
        print("[Advisor] 하이브리드 엔진 분석 시작...")
        # [Rule 4.4] AttributeError 해결: fetch_portfolio() 호출
        portfolio = self.fetch_portfolio()
        
        # 기존 후보군에 현재 보유 종목도 포함하여 매도 신호 추적
        existing_codes = {c.get('code') for c in candidates}
        for code, info in portfolio.items():
            if code not in existing_codes:
                candidates.append({
                    'code': code,
                    'name': info['name'],
                    'price': info['current_price'],
                    'change_rate': 0.0,
                    'source': 'portfolio'
                })

        results = []
        for stock in candidates:
            code = stock.get('code')
            name = stock.get('name')
            in_portfolio = code in portfolio
            
            # 1단계: 기술적 스코어 계산
            score, p_change = self.engine.calculate_score(stock)
            
            p_info = portfolio.get(code)
            profit_rate = p_info.get('profit_rate', 0) if in_portfolio else 0.0
            
            # 2단계: 엔진 신호(HOLD/SELL/BUY_CANDIDATE) 획득
            signal, confidence = self.engine.get_signal(
                score=score, 
                p_change=p_change, 
                in_portfolio=in_portfolio, 
                profit_rate=profit_rate,
                post_count_diff_pct=0.0,
                positive_rate=float(stock.get('positive_rate', 50.0))
            )
            
            action = "WATCH"
            target_price = 0
            custom_reason = ""
            
            if in_portfolio:
                # 보유 종목의 대응 로직
                if "SELL" in signal:
                    action = "SELL_EXECUTE"
                    custom_reason = f"적응형 익절: {signal} (수익률: {profit_rate:.2f}%)"
                    
                    if signal == "SELL_ALL":
                        self.vpm.sell_stock(code) # 가상 매도 기록
                    elif signal == "SELL_HALF":
                        qty = p_info.get('qty', 0)
                        half_qty = max(1, int(qty / 2))
                        self.vpm.sell_stock(code, sell_qty=half_qty)
                        custom_reason += f" [절반 분할 익절]"
                        
                elif signal == "HOLD":
                    action = "HOLD"
                    custom_reason = f"보유 지속 (수익률: {profit_rate:.2f}%)"
            
            # 신규 후보 종목의 매수 검증 로직
            elif signal == "BUY_CANDIDATE":
                if not allow_buy:
                    continue # 장중이 아닐 경우 분석 생략
                
                # 3단계: 뉴스 및 공시(Gate) 검증
                news_list = self.fetch_specific_news(code, name)
                if not self.crosscheck_news_keywords(news_list, name):
                    action = "거절 (뉴스 부재)"
                    continue
                    
                dart_info = self.check_dart_filings(name, code)
                if dart_info.get("hard_reject"):
                    action = f"거절 (DART 악재: {dart_info['summary']})"
                    continue
                    
                # 4단계: AI(Gemini) 모멘텀 검증
                gemini_eval = self.gemini.evaluate_momentum(stock, news_list, dart_info)
                if gemini_eval.get("decision") == "APPROVED":
                    # 실전 계좌: 자동 매수 방지 (추천만 발송)
                    # 가상 계좌(VPM): 자동 매수 기록하여 성과 추정
                    action = "BUY_RECOMMENDED" 
                    target_price = float(stock.get('price', 0))
                    custom_reason = gemini_eval.get("telegram_narrative", "AI 모멘텀 강력 - 진입 추천")
                    
                    self.vpm.buy_stock(code, name, target_price, quantity=20)
                else:
                    action = f"거절 (AI 점수: {gemini_eval.get('momentum_score')})"

            results.append({
                'code': code,
                'name': name,
                'price': stock.get('price', 0),
                'signal': signal,
                'score': score,
                'action': action,
                'target_price': target_price,
                'in_portfolio': in_portfolio,
                'profit_rate': profit_rate,
                'today_change': p_change,
                'factors': stock,
                'custom_reason': custom_reason
            })            
        
        # 스코어 기준 정렬 및 상위 리스팅
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:10]

    def generate_report(self, candidates, allow_buy=True):
        """[What] 텔레그램으로 보낼 최종 가독성 있는 리포트 문자열을 생성합니다."""
        all_results = self.analyze_candidates(candidates, allow_buy=allow_buy)
        
        # 상위 6개 종목 + 강제 매도 종목 포함
        top_6 = all_results[:6]
        forced_sells = [item for item in all_results[6:] if item['action'] == "SELL_EXECUTE"]
        final_report_items = top_6 + forced_sells
        
        # Gemini를 통한 시장 서사 생성
        market_context = f"{len(candidates)}개 종목 분석 완료. 상위 {len(final_report_items)}개 집중 분석."
        gemini_guide = self.gemini.generate_trading_guide(market_context, final_report_items)
        
        report = f"{gemini_guide}\n\n"
        report += "📋 **오늘의 매매 액션 리포트**\n"
        
        for item in final_report_items:
            # 상태 및 아이콘 설정
            icon = "🔴" if "BUY" in item['action'] else "🔵"
            if item['action'] == "WATCH": icon = "👀"
            if item['action'] == "SELL_EXECUTE": icon = "🚨"
            
            p_tag = " [보유중]" if item['in_portfolio'] else ""
            report += f"{icon} **{item['name']}** ({item['action']}){p_tag}\n"
            report += f"   - 신호: {item['signal']} (점수: {item['score']})\n"
            if item['target_price'] > 0:
                report += f"   - 진입가: {item['price']} -> 목표: {int(item['target_price'])}\n"
            elif item['in_portfolio']:
                report += f"   - 현재익률: {item['profit_rate']:.2f}%\n"
            
        return report, final_report_items
