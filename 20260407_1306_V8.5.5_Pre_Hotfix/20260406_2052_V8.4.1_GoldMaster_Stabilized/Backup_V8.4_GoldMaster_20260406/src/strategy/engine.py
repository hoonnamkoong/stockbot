import json
import datetime
from src.strategy.monthly.algo_04_v2 import Algo04V2
from src.strategy.virtual_portfolio import VirtualPortfolioManager
# from src.strategy.advisor import GeminiAgent (순환 참조 방지 Lazy Loading)
import requests
from bs4 import BeautifulSoup

class StrategyEngine:
    """
    [V2 Architecture] 4월 전략 전담 실행 엔진.
    데이터 수집(사이드 이펙트) 및 전략 객체 호출을 담당합니다.
    """
    def __init__(self):
        # 4월 어텐션 모멘텀 전략 주입 (Strategy Pattern)
        from src.strategy.advisor import GeminiAgent
        self.strategy = Algo04V2()
        self.vpm = VirtualPortfolioManager()
        self.gemini = GeminiAgent()
        
    def execute_simulation(self, candidates, allow_buy=True):
        """
        메인 시뮬레이션 루프. 
        전략 모듈에서 받은 판단으로 실제 I/O(매수/매도/로그)를 수행합니다.
        """
        results = []
        portfolio = self.vpm.get_portfolio()
        balance = self.vpm.get_balance()
        
        for stock in candidates:
            code = stock.get('code')
            name = stock.get('name')
            in_portfolio = code in portfolio
            
            # [Step 1] 보유 종목 대응 (Adaptive Exit)
            if in_portfolio:
                prev_post_cnt = 0 # (실제 구현 시 히스토리 데이터 로드 필요)
                signal_data = self.strategy.check_exit_signal(
                    holding_data=portfolio[code],
                    stock_data=stock,
                    prev_post_count=prev_post_cnt
                )
                
                action = signal_data['action']
                if action == "SELL_ALL":
                    self.vpm.sell_stock(code, current_price=float(stock.get('price', 0)))
                elif action == "SELL_HALF":
                    qty = portfolio[code].get('quantity', 0)
                    self.vpm.sell_stock(
                        code, 
                        current_price=float(stock.get('price', 0)), 
                        sell_qty=max(1, int(qty / 2))
                    )
                
                results.append({
                    'code': code, 'name': name, 'signal': action,
                    'reason': signal_data['reason'], 'in_portfolio': True
                })
                continue
                
            # [Step 2] 신규 후보 분석 (2차 검증 + AI)
            if allow_buy:
                # 2-1. [I/O] 2차 검증 오버레이 (DART/News) 데이터 수집
                dart_data = self.fetch_dart_data(code)
                news_list = self.fetch_news_data(code, name)
                
                # 2-2. [I/O] Gemini V2 AI 최종 승인 대기
                llm_decision = self.gemini.evaluate_momentum(stock, news_list, dart_data)
                
                # [지시사항] 무료 티어 15 RPM 제한 준수를 위한 4초 강제 지연
                import time
                time.sleep(4)
                
                # 2-3. [Pure Logic] 전략 모듈 호출 (No I/O inside)
                decision = self.strategy.analyze_target(
                    stock_data=stock,
                    dart_data=dart_data,
                    llm_decision=llm_decision,
                    current_cash=balance['cash']
                )
                
                if decision['action'] == "BUY":
                    # [I/O] 시뮬레이션 매수 집행
                    self.vpm.buy_stock(
                        code=code, name=name, 
                        price=float(stock.get('price', 0)),
                        quantity=decision['quantity'] # 전략이 계산한 수량 사용
                    )
                
                results.append({
                    'code': code, 'name': name, 'signal': decision['action'],
                    'reason': decision.get('reason', '관망'), 'in_portfolio': False
                })

        return results

    def fetch_dart_data(self, code):
        # [I/O 전담] DART 데이터 수집 로직
        # (기존 advisor.py에서 이관된 공시 파싱 로직)
        try:
            url = f"https://finance.naver.com/item/news_notice.naver?code={code}"
            res = requests.get(url, timeout=5)
            soup = BeautifulSoup(res.text, 'html.parser')
            today_str = datetime.datetime.now().strftime('%Y.%m.%d')
            reject_kws = ["전환사채", "신주인수권부사채", "유상증자"]
            
            for row in soup.select('tr'):
                date_td = row.select_one('.date')
                title_a = row.select_one('.title a')
                if date_td and title_a and today_str in date_td.get_text():
                    text = title_a.get_text()
                    if any(k in text for k in reject_kws):
                        return {"reject": True, "reason": f"DART 악재({text})"}
            return {"reject": False}
        except: return {"reject": False}

    def fetch_news_data(self, code, name):
        # [I/O 전담] 뉴스 데이터 수집 로직
        return [] # TODO: Implement real news fetcher
