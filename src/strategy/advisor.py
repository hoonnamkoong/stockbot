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
        load_env()
        # [Rule 4.1] 하드코딩 금지: 환경 변수에서 키 로드
        self.api_key = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_KEY')
        self.model = None
        
        if self.api_key:
            genai.configure(api_key=self.api_key)
            # [Update] 사용자 지시사항: 2.0/2.5급 최고 사양 모델로 교체
            # Python SDK에서 2.5는 gemini-2.0-pro-exp 또는 gemini-2.0-flash로 대응
            models_to_try = [
                'gemini-2.0-pro-exp-0205',  # 최상위 실험적 모델
                'gemini-2.0-flash',         # 최고 성능/속도
                'gemini-1.5-pro'            # 안정적인 상위 모델
            ]
            
            for m in models_to_try:
                try:
                    # [Step] 모델 초기화 시도
                    model_obj = genai.GenerativeModel(m)
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
        당신은 실전 주식 투자 전문가입니다. 
        다음 데이터와 신호를 바탕으로 오늘의 시장 상황을 요약하고, 투자자들에게 주는 핵심 권고 사항을 작성하세요.
        
        데이터:
        - 시장 상황: {market_context}
        - 주요 신호: {json.dumps(sentinel_signals, ensure_ascii=False)}
        
        요구사항:
        1. 첫 문장은 시장의 '분의기(Regime)'를 한 문장으로 정의하며 시작하세요.
        2. 왜 특정 종목을 보유(HOLD)하거나 매도(SELL)해야 하는지 논리적으로 설명하세요.
        3. '입니다/합니다'체를 사용하며 신뢰감 있는 톤으로 작성하세요.
        4. 수치 데이터를 근거로 제시하세요.
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
            
            # [지시사항 1] 기술적/어텐션 1차 필터 통과 여부 확인
            passed, p_change = self.engine.is_v2_target_passed(stock)
            
            p_info = portfolio.get(code)
            profit_rate = p_info.get('profit_rate', 0) if in_portfolio else 0.0
            
            # [지시사항 4] 4월 V2 매도 룰 적용
            prev_post_count = 0 # (실제 구현 시 이전 날짜 데이터 로드 로직 필요)
            signal, reason = self.engine.get_signal(
                stock_data=stock, 
                in_portfolio=in_portfolio, 
                profit_rate=profit_rate,
                prev_post_count=prev_post_count
            )
            
            action = "WATCH"
            target_price = 0
            custom_reason = ""
            
            if in_portfolio:
                if signal == "SELL_ALL":
                    action = "SELL_EXECUTE"
                    custom_reason = f"🚨 {reason} (수익률: {profit_rate:.2f}%)"
                    self.vpm.sell_stock(code) # 가상 시뮬레이터 매도
                elif signal == "SELL_HALF":
                    action = "PARTIAL_SELL"
                    qty = p_info.get('qty', 0)
                    half_qty = max(1, int(qty / 2))
                    custom_reason = f"⚠️ {reason} (+10% 익절, 50% 매도)"
                    self.vpm.sell_stock(code, sell_qty=half_qty)
                elif signal == "HOLD":
                    action = "HOLD"
                    custom_reason = f"보유 지속 (수익률: {profit_rate:.2f}%)"
            
            # [지시사항 2, 3] 신규 후보 종목의 2차 검증 및 AI 승인
            elif passed and allow_buy:
                # 2-1. 뉴스 0건 체크
                news_list = self.fetch_specific_news(code, name)
                if len(news_list) == 0:
                    action = "REJECTED (뉴스 0건)"
                    continue
                    
                # 2-2. DART 오늘 자 악재 공시 체크
                dart_info = self.check_dart_filings(name, code)
                if dart_info.get("reject"):
                    action = f"REJECTED ({dart_info['reason']})"
                    continue
                    
                # 3. Gemini V2 AI 최종 승인 (JSON 강제)
                gemini_eval = self.gemini.evaluate_momentum(stock, news_list, dart_info)
                if gemini_eval.get("decision") == "APPROVED":
                    # [지시사항 5] 자금 운용 및 포지션 사이징은 vpm.buy_stock 내부에서 처리
                    action = "BUY_RECOMMENDED" 
                    target_price = float(stock.get('price', 0))
                    custom_reason = gemini_eval.get("telegram_narrative", "AI 승인됨")
                    
                    # [V2] 가상 자산 규칙에 따른 매수 집행
                    self.vpm.buy_stock(code, name, target_price) 
                else:
                    action = "REJECTED (AI 분석 미승인)"
                    custom_reason = gemini_eval.get("telegram_narrative", "모멘텀 부족")

            results.append({
                'code': code,
                'name': name,
                'price': stock.get('price', 0),
                'signal': signal,
                'action': action,
                'target_price': target_price,
                'in_portfolio': in_portfolio,
                'profit_rate': profit_rate,
                'custom_reason': custom_reason
            })            
        
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
        
        try:
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
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"[Advisor] Critical Report Generation Error: {e}")
            return f"⚠️ **가이드 생성 중 오류가 발생했습니다.**\n\n**원인:** {str(e)}\n\n**상세:**\n```\n{error_details[:500]}\n```", []
