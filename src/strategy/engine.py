import json
import datetime
from src.strategy.strategy_loader import load_monthly_strategy
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
        self.strategy = load_monthly_strategy()
        self.vpm = VirtualPortfolioManager()
        self.gemini = GeminiAgent()
        
    def execute_simulation(self, candidates, allow_buy=True):
        """ Legacy Simulation Logic (Reserved for potential combined mode) """
        return self.execute_sandbox_simulation(candidates, allow_buy)

    def execute_sandbox_simulation(self, candidates, allow_buy=True):
        """
        [V8.5.4] KIS 실계좌와 100% 단절된 샌드박스 시뮬레이터
        - KIS API 호출 로직이 물리적으로 제거됨.
        - 오직 가상 계좌(VirtualPortfolioManager) 내에서만 숫자가 변동됨.
        """
        results = []
        portfolio = self.vpm.get_portfolio()
        balance = self.vpm.get_balance()
        
        print(f"[Sandbox] 가상 포트폴리오 매매 프로세스 시작 (잔고: {balance.get('cash', 0):,}원)")
        
        for stock in candidates:
            code = stock.get('code')
            name = stock.get('name')
            in_portfolio = code in portfolio
            
            # [Step 1] 보유 종목 대응 (Adaptive Exit)
            if in_portfolio:
                # 알고리즘 명세 기반 매도 신호 체크
                signal_data = self.strategy.check_exit_signal(
                    holding_data=portfolio[code],
                    stock_data=stock,
                    prev_post_count=0 # TODO: 이전 Buzz 데이터 연동
                )
                
                action = signal_data['action']
                if action == "SELL_ALL":
                    self.vpm.sell_stock(code, current_price=float(stock.get('price', 0)))
                    print(f"   [Simulation] 전량 매도: {name}")
                elif action == "SELL_HALF":
                    qty = portfolio[code].get('quantity', 0)
                    self.vpm.sell_stock(
                        code, 
                        current_price=float(stock.get('price', 0)), 
                        sell_qty=max(1, int(qty / 2))
                    )
                    print(f"   [Simulation] 반량 매도(50%): {name}")
                
                results.append({
                    'code': code, 'name': name, 'signal': action,
                    'reason': signal_data['reason'], 'in_portfolio': True
                })
                continue
                
            # [Step 2] 신규 후보 분석 및 가상 매수
            if allow_buy:
                # 3차 필터링을 통과한 종목에 대해서만 시뮬레이션 집행
                # (매수 조건: Algo04V2 내부에 2차/3차 필터 로직 포함)
                dart_info = self.fetch_dart_data(code)
                decision = self.strategy.analyze_target(
                    stock_data=stock,
                    dart_data=dart_info,
                    llm_decision={"decision": "APPROVED", "telegram_narrative": "Sandbox Simulation"},
                    current_cash=balance['cash']
                )
                
                if decision['action'] == "BUY":
                    # KIS API 절대 호출 금지 - 오직 VPM만 사용
                    self.vpm.buy_stock(
                        code=code, name=name, 
                        price=float(stock.get('price', 0)),
                        quantity=decision['quantity']
                    )
                    print(f"   [Simulation] 가상 매수 체결: {name} ({decision['quantity']}주)")
                
                results.append({
                    'code': code, 'name': name, 'signal': decision['action'],
                    'reason': decision.get('reason', '관망'), 'in_portfolio': False
                })
            else:
                results.append({
                    'code': code, 'name': name, 'signal': 'WATCH',
                    'reason': '비거래 시간대 분석', 'in_portfolio': False
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
            return {"reject": False, "reason": "특이 공시 없음"}
        except: return {"reject": False, "reason": "DART 모니터링 일시 중단"}
