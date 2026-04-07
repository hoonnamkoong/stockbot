import json
import os
import datetime
import requests
from bs4 import BeautifulSoup
from .base_simulator import BaseSimulator

class AggressiveSimulator(BaseSimulator):
    """
    [Sim 2] 공격형 - 하이퍼-볼래틸리티 돌파 전략
    - 래리 윌리엄스의 변동성 돌파 전략 기반
    - 진입: 당일 시가 + (전일 변동폭 * 0.4) 돌파 시 50~100% 집중 베팅
    - 피라미딩: +3% 수익 시 추가 매수
    - 청산: 고점 대비 -2% 트레일링 스탑 & 15:15 전량 매도
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("Aggressive", initial_cash)

    def fetch_market_data(self, code):
        """
        [Real-time] 네이버 금융 실시간 시세 (시가, 고가, 저가 등)
        """
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        try:
            res = requests.get(url, timeout=5)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # 현재가 파싱
            rate_info = soup.select_one(".no_today")
            current_price = int(rate_info.select_one(".blind").text.replace(",", ""))
            
            # 전일 고가/저가/시가 파싱
            table = soup.select_one(".no_info")
            blind_list = table.select(".blind")
            
            prev_close = int(blind_list[0].text.replace(",", ""))
            today_open = int(blind_list[1].text.replace(",", ""))
            
            # [V8.5.3] 전일 변동폭 (정규 변동폭 대체 로직: 전일 종가의 5%)
            # 실제 전일 고가/저가 데이터를 가져오려면 /item/sise.naver 페이지 방문 권장
            return {
                "current": current_price,
                "open": today_open,
                "prev_range": (prev_close * 0.05)
            }
        except:
            return None

    def execute_strategy(self, candidates):
        if not candidates or len(self.state['portfolio']) >= 2: return
        
        for stock in candidates[:3]: # 최상위 3개 종목만 검토
            code = stock['code']
            if code in self.state['portfolio']: continue
            
            m_data = self.fetch_market_data(code)
            if not m_data: continue
            
            current_price = m_data['current']
            today_open = m_data['open']
            prev_range = m_data['prev_range']
            
            target_price = today_open + (prev_range * 0.4)
            
            if current_price >= target_price:
                # 50~100% 비중 베팅
                bet_amount = self.state['cash'] * 0.95
                qty = int(bet_amount / current_price)
                if qty > 0:
                    reason = f"[공격형] 변동성 돌파({target_price:,.0f}원) 상향 도달 시점 집중 베팅"
                    if self.buy(code, stock['name'], current_price, qty, reason=reason):
                        self.state['portfolio'][code]['peak_price'] = current_price
                        print(f"[Sim 2] {stock['name']} 돌파 매수")

    def check_maintenance(self):
        """ 주기적 호출 (트레일링 스탑, 피라미딩, 타임 컷) """
        now = datetime.datetime.now()
        
        # 1. 타임 컷 (15:15 오버나잇 금지)
        if now.hour == 15 and now.minute >= 15:
            codes = list(self.state['portfolio'].keys())
            for c in codes:
                m_data = self.fetch_market_data(c)
                price = m_data['current'] if m_data else self.state['portfolio'][c]['price']
                self.sell(c, price, reason="[공격형] 당일 매수 당일 청산 (Time-Cut)")
            return

        # 2. 사후 관리
        codes = list(self.state['portfolio'].keys())
        for code in codes:
            item = self.state['portfolio'][code]
            m_data = self.fetch_market_data(code)
            if not m_data: continue
            
            price = m_data['current']
            # 최고가 관리
            if price > item.get('peak_price', 0):
                self.state['portfolio'][code]['peak_price'] = price
                
            # 트레일링 스탑 (-2%)
            peak = item.get('peak_price', price)
            if price <= (peak * 0.98):
                self.sell(code, price, reason=f"[공격형] 최고점({peak:,.0f}) 대비 -2% 하락 트레일링 스탑")
                continue
                
            # 피라미딩 (+3% 시 50% 추가 매수)
            avg_p = item['price']
            if price >= (avg_p * 1.03) and not item.get('pyramided', False):
                add_qty = int((self.state['cash'] * 0.5) / price)
                if add_qty > 0:
                    if self.buy(code, item['name'], price, add_qty, reason="[공격형] 수익 3% 돌파 시 추세 강화 피라미딩"):
                        self.state['portfolio'][code]['pyramided'] = True
