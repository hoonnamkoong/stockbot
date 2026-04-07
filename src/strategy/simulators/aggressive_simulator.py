import json
import os
import datetime
import requests
from bs4 import BeautifulSoup
from .base_simulator import BaseSimulator

class AggressiveSimulator(BaseSimulator):
    """
    [Sim 3] 하이퍼-볼래틸리티 돌파 전략
    - 래리 윌리엄스의 변동성 돌파 전략 기반
    - 진입: 당일 시가 + (전일 변동폭 * 0.4) 돌파 시 50~100% 집중 베팅
    - 피라미딩: +3% 수익 시 추가 매수
    - 청산: 고점 대비 -2% 트레일링 스탑 & 15:15 전량 매도
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("Aggressive", initial_cash)

    def fetch_market_data(self, code):
        """
        [Real-time] 네이버 금융을 통해 종목의 실시간 시세 및 전일 데이터를 조회합니다.
        필요 데이터: 전일 고가, 전일 저가, 당일 시가, 현재가
        """
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        try:
            res = requests.get(url, timeout=5)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # 현재가, 시가, 고가, 저가 등 추출 (네이버 금융 구조 기준)
            # blind 태그 내의 텍스트 추출
            new_total = soup.select_one(".new_totalinfo")
            if not new_total: return None
            
            # [필수 데이터 추출]
            # 실시간 데이터는 다른 영역에서 더 정확히 가져올 수 있음
            # 여기서는 시뮬레이션 목적상 기본 시세 영역 사용
            # (실제 운영 시에는 KIS API 또는 더 정교한 크롤러 권장)
            
            # 단순화를 위해 기존 analyzer의 수집 데이터가 없을 때만 실시간 크롤링 시도
            # 여기서는 구조적 예시를 작성하며, 실제 작동을 위해 KIS API 활용도 고려 가능
            # 네이버 금융 실전 데이터 파싱
            rate_info = soup.select_one(".no_today")
            current_price = int(rate_info.select_one(".blind").text.replace(",", ""))
            
            # 전일 고가/저가/시가 정보 추출 (table 영역)
            table = soup.select_one(".no_info")
            blind_list = table.select(".blind") # 전일, 시가, 고가, 저가 순
            
            prev_close = int(blind_list[0].text.replace(",", ""))
            today_open = int(blind_list[1].text.replace(",", ""))
            # yesterday_high, yesterday_low는 main 페이지에 없을 수 있으므로 상세 시세 페이지 필요할 수 있음
            # 우선은 '전일' 데이터를 기준으로 변동폭 목업 또는 추가 크롤링
            
            return {
                "current": current_price,
                "open": today_open,
                "prev_range": (prev_close * 0.05) # 임시: 전일 변동폭을 알 수 없을 때 5%로 가정
            }
        except:
            return None

    def execute_strategy(self, candidates):
        """
        [Algorithm] 변동성 돌파 & 집중 베팅
        candidates: 1차 Buzz Filter 통과 종목
        """
        if not candidates: return
        
        # 가용한 슬롯이 1~2개인지 확인
        if len(self.state['portfolio']) >= 2: return
        
        # 거래대금 상위 2개 종목만 분석
        # (candidates가 이미 거래대금 순으로 정렬되어 있다고 가정)
        for stock in candidates[:5]: 
            code = stock['code']
            if code in self.state['portfolio']: continue
            
            # 실시간 데이터 조회
            m_data = self.fetch_market_data(code)
            if not m_data: continue
            
            current_price = m_data['current']
            today_open = m_data['open']
            prev_range = m_data.get('prev_range', 0) # 전일 변동폭 (고-저)
            
            # 돌파 기준가: 시가 + (전일변동폭 * 0.4)
            target_price = today_open + (prev_range * 0.4)
            
            if current_price >= target_price:
                # [집중 베팅] 가용 현금의 50~100% 매수
                # 종목당 슬롯 2개라고 가정 시 현금의 50%
                available_cash = self.state['cash'] * 0.95
                if len(self.state['portfolio']) == 0:
                    bet_amount = available_cash # 첫 종목이면 100% 가깝게
                else:
                    bet_amount = available_cash # 남은 현금 100%
                
                qty = int(bet_amount / current_price)
                if qty > 0:
                    reason = f"[변동성 돌파] 돌파가 {target_price:,.0f}원 도달 (현재:{current_price:,.0f})"
                    if self.buy(code, stock['name'], current_price, qty, reason=reason):
                        # 매수 시점에 최고가 초기화
                        self.state['portfolio'][code]['peak_price'] = current_price
                        print(f"[Aggressive] 🚀 {stock['name']} 돌파 매수 완료")

    def check_pyramiding_and_stop(self, current_stocks_data):
        """
        [Dynamic] 15~30분 주기 모니터링 시 호출
        - 피라미딩(불타기)
        - 트레일링 스탑
        - 타임 컷 (15:15)
        """
        now = datetime.datetime.now()
        # 1. 타임 컷 (15:15 이후)
        if now.hour == 15 and now.minute >= 15:
            codes = list(self.state['portfolio'].keys())
            for code in codes:
                m_data = self.fetch_market_data(code)
                price = m_data['current'] if m_data else self.state['portfolio'][code]['price']
                self.sell(code, price, reason="[타임 컷] 장 마감 전 오버나잇 방지 강제 청산")
            return

        # 2. 피라미딩 & 트레일링 스탑 로직
        codes = list(self.state['portfolio'].keys())
        for code in codes:
            item = self.state['portfolio'][code]
            m_data = self.fetch_market_data(code)
            if not m_data: continue
            
            current_price = m_data['current']
            
            # 최고가 갱신
            if current_price > item.get('peak_price', 0):
                self.state['portfolio'][code]['peak_price'] = current_price
            
            # A. 트레일링 스탑 (최고점 대비 -2% 하락)
            peak = item.get('peak_price', current_price)
            if current_price <= (peak * 0.98):
                self.sell(code, current_price, reason=f"[트레일링 스탑] 최고점({peak:,.0f}) 대비 -2% 하락 이탈")
                continue
                
            # B. 피라미딩 (평단가 대비 +3% 상승 시 남은 현금의 절반 추가 매수)
            avg_price = item['price']
            if current_price >= (avg_price * 1.03) and self.state['cash'] > 100000:
                # 아직 추가 매수를 안 했을 때만 (단순화를 위해 추가 매수 여부 체크 필드 사용 고려)
                if not item.get('pyramided', False):
                    add_amount = self.state['cash'] * 0.5
                    add_qty = int(add_amount / current_price)
                    if add_qty > 0:
                        if self.buy(code, item['name'], current_price, add_qty, reason="[피라미딩] 수익구간 추세 강화 추가 매입"):
                            self.state['portfolio'][code]['pyramided'] = True
                            print(f"[Aggressive] 🔥 {item['name']} 피라미딩 완료")
        
        self.save_state()
